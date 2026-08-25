import {
  createPublicServiceClient,
  type components,
} from "@82ta/service-client";

export type PublicRouteSearchRequest = components["schemas"]["PublicRouteSearchRequest"];
export type PublicRouteSearchResponse = components["schemas"]["PublicRouteSearchResponse"];
export type PublicProblem = components["schemas"]["ProblemDetails"];
export type RouteCandidate = components["schemas"]["RouteCandidate"];
export type RouteLeg = components["schemas"]["RouteLeg"];
export type PublicCapabilities = components["schemas"]["PublicCapabilities"];
export type PlaceRef = components["schemas"]["PlaceRef"];
export type UserPreferences = components["schemas"]["UserPreferences"];
export type SavedPlace = components["schemas"]["SavedPlace"];
export type SavedPlaceInput = components["schemas"]["SavedPlaceInput"];
export type FavoriteJourney = components["schemas"]["FavoriteJourney"];
export type FavoriteJourneyInput = components["schemas"]["FavoriteJourneyInput"];
export type FavoriteJourneyFromPlacesInput = components["schemas"]["FavoriteJourneyFromPlacesInput"];
export type FavoriteJourneyFromPlacesResult = components["schemas"]["FavoriteJourneyFromPlacesResult"];
export type FavoriteJourneySearchConditionsV1 = components["schemas"]["FavoriteJourneySearchConditionsV1"];
export type RouteFeedbackInput = components["schemas"]["RouteFeedbackInput"];
export type GuestSessionCredential = components["schemas"]["GuestSessionCredential"];
export type SessionContext = components["schemas"]["SessionContext"];
export type EmailCredentialInput = components["schemas"]["EmailCredentialInput"];
export type EmailRegistrationInput = components["schemas"]["EmailRegistrationInput"];
export type SavedPlaceUpdate = components["schemas"]["SavedPlaceUpdate"];
export type FavoriteJourneyUpdate = components["schemas"]["FavoriteJourneyUpdate"];
export type ConsentType = components["schemas"]["ConsentType"];
export type ConsentInput = components["schemas"]["ConsentInput"];
export type ConsentRecord = components["schemas"]["ConsentRecord"];
export type DataRightsJob = components["schemas"]["DataRightsJob"];

const client = () => createPublicServiceClient(window.location.origin);

function requestKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function createIdempotencyKey(): string {
  return requestKey();
}

function csrfTokenFromCookie(): string | null {
  const prefix = "csrftoken=";
  const encodedToken = document.cookie
    .split(";")
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith(prefix))
    ?.slice(prefix.length);

  if (encodedToken === undefined || encodedToken.length === 0) return null;

  try {
    return decodeURIComponent(encodedToken);
  } catch {
    return null;
  }
}

async function mutationHeaders(): Promise<Record<string, string>> {
  const health = await client().GET("/api/v1/health", { credentials: "same-origin" });
  if (!health.response.ok) throw new Error("CSRF bootstrap failed");

  const token = csrfTokenFromCookie();
  if (token === null) throw new Error("CSRF cookie missing");
  return { "X-CSRFToken": token };
}

export async function createRouteSearch(body: PublicRouteSearchRequest, idempotencyKey = requestKey()) {
  return client().POST("/api/v1/route-searches", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    params: {
      header: {
        "Idempotency-Key": idempotencyKey,
        "X-Correlation-Id": requestKey(),
      },
    },
    body,
  });
}

export async function createGuestSession() {
  return client().POST("/api/v1/guest-sessions", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
  });
}

export async function registerWithEmail(body: EmailRegistrationInput) {
  return client().POST("/api/v1/auth/register", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    body,
  });
}

export async function loginWithEmail(body: EmailCredentialInput) {
  return client().POST("/api/v1/auth/login", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    body,
  });
}

export async function getCurrentSession(guestToken?: string) {
  return client().GET("/api/v1/session", {
    credentials: "same-origin",
    ...(guestToken === undefined ? {} : { headers: { "X-Guest-Token": guestToken } }),
  });
}

export async function revokeCurrentSession(guestToken?: string) {
  return client().DELETE("/api/v1/session", {
    credentials: "same-origin",
    headers: {
      ...(await mutationHeaders()),
      ...(guestToken === undefined ? {} : { "X-Guest-Token": guestToken }),
    },
  });
}

export async function suggestPlaces(query: string, near?: PlaceRef["coordinate"]) {
  return client().GET("/api/v1/places/suggest", {
    credentials: "same-origin",
    params: {
      query: {
        query,
        ...(near === undefined ? {} : { lon: near.lon, lat: near.lat }),
      },
    },
  });
}

export async function reverseGeocode(coordinate: PlaceRef["coordinate"]) {
  return client().GET("/api/v1/places/reverse-geocode", {
    credentials: "same-origin",
    params: { query: coordinate },
  });
}

export async function listRouteSearches() {
  return client().GET("/api/v1/route-searches", { credentials: "same-origin" });
}

export async function getRouteSearch(searchId: string, guestToken?: string) {
  return client().GET("/api/v1/route-searches/{searchId}", {
    credentials: "same-origin",
    params: {
      path: { searchId },
      ...(guestToken === undefined ? {} : { header: { "X-Guest-Token": guestToken } }),
    },
  });
}

export async function getPreferences() {
  return client().GET("/api/v1/me/preferences", { credentials: "same-origin" });
}

export async function updatePreferences(body: UserPreferences, etag?: string) {
  return client().PUT("/api/v1/me/preferences", {
    credentials: "same-origin",
    headers: {
      ...(await mutationHeaders()),
      ...(etag === undefined ? {} : { "If-Match": etag }),
    },
    body,
  });
}

export async function listSavedPlaces() {
  return client().GET("/api/v1/me/saved-places", { credentials: "same-origin" });
}

export async function createSavedPlace(body: SavedPlaceInput) {
  return client().POST("/api/v1/me/saved-places", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    body,
  });
}

export async function updateSavedPlace(savedPlaceId: string, body: SavedPlaceUpdate) {
  return client().PATCH("/api/v1/me/saved-places/{savedPlaceId}", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    params: { path: { savedPlaceId } },
    body,
  });
}

export async function deleteSavedPlace(savedPlaceId: string) {
  return client().DELETE("/api/v1/me/saved-places/{savedPlaceId}", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    params: { path: { savedPlaceId } },
  });
}

export async function listFavoriteJourneys() {
  return client().GET("/api/v1/me/favorite-journeys", { credentials: "same-origin" });
}

export async function createFavoriteJourney(body: FavoriteJourneyInput) {
  return client().POST("/api/v1/me/favorite-journeys", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    body,
  });
}

export async function createFavoriteJourneyFromPlaces(body: FavoriteJourneyFromPlacesInput, idempotencyKey = requestKey()) {
  return client().POST("/api/v1/me/favorite-journeys/from-places", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    params: { header: { "Idempotency-Key": idempotencyKey } },
    body,
  });
}

export async function updateFavoriteJourney(favoriteJourneyId: string, body: FavoriteJourneyUpdate) {
  return client().PATCH("/api/v1/me/favorite-journeys/{favoriteJourneyId}", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    params: { path: { favoriteJourneyId } },
    body,
  });
}

export async function deleteFavoriteJourney(favoriteJourneyId: string) {
  return client().DELETE("/api/v1/me/favorite-journeys/{favoriteJourneyId}", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    params: { path: { favoriteJourneyId } },
  });
}

export async function listConsents() {
  return client().GET("/api/v1/me/consents", { credentials: "same-origin" });
}

export async function recordConsent(consentType: ConsentType, body: ConsentInput) {
  return client().PUT("/api/v1/me/consents/{consentType}", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
    params: { path: { consentType } },
    body,
  });
}

export async function createDataExport() {
  return client().POST("/api/v1/me/data-exports", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
  });
}

export async function getDataExport(jobId: string) {
  return client().GET("/api/v1/me/data-exports/{jobId}", {
    credentials: "same-origin",
    params: { path: { jobId } },
  });
}

export async function createDataDeletion() {
  return client().POST("/api/v1/me/data-deletions", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
  });
}

export async function getDataDeletion(jobId: string) {
  return client().GET("/api/v1/me/data-deletions/{jobId}", {
    credentials: "same-origin",
    params: { path: { jobId } },
  });
}

export async function getPublicCapabilities() {
  return client().GET("/api/v1/support/capabilities", { credentials: "same-origin" });
}

export async function submitRouteFeedback(searchId: string, body: RouteFeedbackInput, guestToken?: string) {
  return client().POST("/api/v1/route-searches/{searchId}/feedback", {
    credentials: "same-origin",
    headers: {
      ...(await mutationHeaders()),
      ...(guestToken === undefined ? {} : { "X-Guest-Token": guestToken }),
    },
    params: { path: { searchId } },
    body,
  });
}

export async function deleteUserData() {
  return client().DELETE("/api/v1/me/data", {
    credentials: "same-origin",
    headers: await mutationHeaders(),
  });
}
