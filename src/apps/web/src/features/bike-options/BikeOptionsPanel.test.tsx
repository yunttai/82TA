import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBikeOptions,
  type BikeOptionsResponse,
  type BikeStationOption,
} from "../../shared/api/publicService";
import { BikeOptionsPanel } from "./BikeOptionsPanel";

vi.mock("../../shared/api/publicService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../shared/api/publicService")>();
  return { ...actual, getBikeOptions: vi.fn() };
});

const origin = { lon: 127.0301, lat: 37.4984 };
const destination = { lon: 126.9733, lat: 37.556 };

function station(id: string, name: string, distanceFromPointMeters: number): BikeStationOption {
  return {
    stationId: id,
    name,
    district: "중구",
    address: `서울시 ${name} 주소`,
    coordinate: { lon: 127, lat: 37.5 },
    rackCount: null,
    distanceFromPointMeters,
  };
}

const successData = {
  pickupStations: [
    station("p1", "추천 출발 대여소", 231),
    station("p2", "출발 후보 2", 300),
    station("p3", "출발 후보 3", 400),
    station("p4", "출발 후보 4", 500),
    station("p5", "표시하지 않을 출발 후보", 600),
  ],
  returnStations: [
    station("r1", "추천 반납 대여소", 94),
    station("r2", "반납 후보 2", 200),
    station("r3", "반납 후보 3", 300),
    station("r4", "반납 후보 4", 400),
    station("r5", "표시하지 않을 반납 후보", 500),
  ],
  rideEstimate: {
    pickupStationId: "p1",
    returnStationId: "r1",
    distanceMeters: 8_122,
    durationSeconds: 1_950,
    assumedSpeedKph: 15,
    distanceMethod: "STRAIGHT_LINE",
  },
  searchRadiusMeters: 5_000,
  stationDataMonth: "2026-06",
  availabilityStatus: "NOT_PROVIDED",
  dataSource: {
    name: "서울특별시 공공자전거 대여소 정보",
    url: "https://data.seoul.go.kr/dataList/OA-13252/F/1/datasetView.do",
    license: "공공누리 제1유형",
    publishedAt: "2026-07-15",
  },
} satisfies BikeOptionsResponse;

function apiResult(data: BikeOptionsResponse, status = 200) {
  return {
    data,
    response: new Response(null, { status }),
  } as Awaited<ReturnType<typeof getBikeOptions>>;
}

describe("BikeOptionsPanel", () => {
  beforeEach(() => {
    vi.mocked(getBikeOptions).mockReset();
  });

  it("announces loading without blocking the route result", () => {
    const pending = new Promise<Awaited<ReturnType<typeof getBikeOptions>>>(() => undefined);
    vi.mocked(getBikeOptions).mockReturnValue(pending);

    render(
      <>
        <p>기존 추천 경로</p>
        <BikeOptionsPanel origin={origin} destination={destination} />
      </>,
    );

    expect(screen.getByText("기존 추천 경로")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("가까운 따릉이 대여소를 찾고 있어요");
    expect(screen.getByRole("region", { name: "따릉이로 이동하기" })).toHaveAttribute("aria-busy", "true");
  });

  it("shows the server estimate, nearest stations, at most three alternatives and required disclosures", async () => {
    vi.mocked(getBikeOptions).mockResolvedValue(apiResult(successData));
    render(<BikeOptionsPanel origin={origin} destination={destination} />);

    const panel = await screen.findByRole("region", { name: "따릉이로 이동하기" });
    expect(within(panel).getByRole("status", { name: "따릉이 단순 주행 예상" })).toHaveTextContent("약 33분");
    expect(within(panel).getByText("약 33분")).toBeVisible();
    expect(within(panel).getByText("8.1km · 시속 15km 기준")).toBeVisible();
    expect(within(panel).getByText("추천 출발 대여소")).toBeVisible();
    expect(within(panel).getByText("추천 반납 대여소")).toBeVisible();
    expect(within(panel).getByText("출발지에서 231m")).toBeVisible();
    expect(within(panel).getByText("목적지에서 94m")).toBeVisible();
    expect(within(panel).getByText("출발 후보 4")).toBeVisible();
    expect(within(panel).getByText("반납 후보 4")).toBeVisible();
    expect(within(panel).queryByText("표시하지 않을 출발 후보")).not.toBeInTheDocument();
    expect(within(panel).queryByText("표시하지 않을 반납 후보")).not.toBeInTheDocument();
    expect(within(panel).getByText("직선거리·시속 15km 단순 예상", { exact: false })).toBeVisible();
    expect(within(panel).getByText("실시간 대여 가능 수량은 따릉이 앱에서 확인", { exact: false })).toBeVisible();
    expect(within(panel).getByText("2026년 6월 기준", { exact: false })).toBeVisible();
    expect(within(panel).getByRole("link", { name: "서울시 데이터 출처 (새 창)" })).toHaveAttribute(
      "href",
      successData.dataSource.url,
    );
  });

  it("renders a distinct empty state with the search radius and source", async () => {
    vi.mocked(getBikeOptions).mockResolvedValue(apiResult({
      ...successData,
      pickupStations: [],
      returnStations: [],
      rideEstimate: null,
    }));
    render(<BikeOptionsPanel origin={origin} destination={destination} />);

    expect(await screen.findByText("가까운 대여소 조합을 찾지 못했어요")).toBeVisible();
    expect(screen.getByText(/반경 5km 안에 서로 다른 대여소가 없습니다/)).toBeVisible();
    expect(screen.getByText("실시간 대여 가능 수량은 따릉이 앱에서 확인", { exact: false })).toBeVisible();
  });

  it("isolates an API failure from the route result and supports retry", async () => {
    const user = userEvent.setup();
    vi.mocked(getBikeOptions)
      .mockRejectedValueOnce(new Error("bike API failed"))
      .mockResolvedValueOnce(apiResult(successData));

    render(
      <>
        <section aria-label="기존 길찾기 결과">추천 경로는 계속 표시됩니다.</section>
        <BikeOptionsPanel origin={origin} destination={destination} />
      </>,
    );

    expect(await screen.findByText("따릉이 정보를 불러오지 못했어요")).toBeVisible();
    expect(screen.getByRole("region", { name: "기존 길찾기 결과" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "따릉이 정보 다시 불러오기" }));
    expect(await screen.findByText("약 33분")).toBeVisible();
    expect(getBikeOptions).toHaveBeenCalledTimes(2);
  });
});
