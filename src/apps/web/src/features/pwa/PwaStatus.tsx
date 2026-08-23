import { useEffect, useRef, useState } from "react";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

function isStandalone(): boolean {
  return window.matchMedia("(display-mode: standalone)").matches
    || ("standalone" in navigator && navigator.standalone === true);
}

export function PwaStatus() {
  const [installPrompt, setInstallPrompt] = useState<InstallPromptEvent | null>(null);
  const [updateWorker, setUpdateWorker] = useState<ServiceWorker | null>(null);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [showIosGuide, setShowIosGuide] = useState(false);
  const [registrationFailed, setRegistrationFailed] = useState(false);
  const updateRequested = useRef(false);
  const iosInstallAvailable = /iphone|ipad|ipod/i.test(navigator.userAgent) && !isStandalone();

  async function registerServiceWorker() {
    if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
    setRegistrationFailed(false);
    try {
      const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      if (registration.waiting !== null) setUpdateWorker(registration.waiting);
      registration.addEventListener("updatefound", () => {
        const worker = registration.installing;
        worker?.addEventListener("statechange", () => {
          if (worker.state === "installed" && navigator.serviceWorker.controller !== null) setUpdateWorker(worker);
        });
      });
    } catch {
      setRegistrationFailed(true);
    }
  }

  useEffect(() => {
    function onInstall(event: Event) {
      event.preventDefault();
      setInstallPrompt(event as InstallPromptEvent);
    }
    function onOnline() { setOffline(false); }
    function onOffline() { setOffline(true); }
    window.addEventListener("beforeinstallprompt", onInstall);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);

    void registerServiceWorker();

    return () => {
      window.removeEventListener("beforeinstallprompt", onInstall);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return undefined;
    function reload() {
      if (updateRequested.current) window.location.reload();
    }
    navigator.serviceWorker.addEventListener("controllerchange", reload);
    return () => navigator.serviceWorker.removeEventListener("controllerchange", reload);
  }, []);

  async function install() {
    if (installPrompt === null) return;
    await installPrompt.prompt();
    await installPrompt.userChoice;
    setInstallPrompt(null);
  }

  function update() {
    if (!window.confirm("새 버전을 적용하면 현재 입력 화면을 다시 불러옵니다. 지금 업데이트할까요?")) return;
    updateRequested.current = true;
    updateWorker?.postMessage({ type: "SKIP_WAITING" });
  }

  if (!offline && installPrompt === null && updateWorker === null && !iosInstallAvailable && !registrationFailed) return null;

  return (
    <aside className="pwa-status" aria-live="polite">
      {offline && <p>오프라인입니다. 앱 화면은 열리지만 새 검색과 계정 데이터는 연결 후 사용할 수 있습니다.</p>}
      {!offline && updateWorker !== null && <><span>새 버전이 준비됐습니다.</span><button type="button" onClick={update}>지금 업데이트</button><button type="button" onClick={() => setUpdateWorker(null)}>나중에</button></>}
      {!offline && registrationFailed && <><span>업데이트를 확인하지 못했습니다. 현재 버전은 계속 사용할 수 있습니다.</span><button type="button" onClick={() => void registerServiceWorker()}>다시 시도</button></>}
      {!offline && installPrompt !== null && !isStandalone() && (
        <button type="button" onClick={() => void install()}>홈 화면에 82TA 설치</button>
      )}
      {!offline && installPrompt === null && iosInstallAvailable && (
        <button type="button" onClick={() => setShowIosGuide((current) => !current)}>iPhone에 설치</button>
      )}
      {showIosGuide && <p>Safari 공유 버튼을 누른 뒤 ‘홈 화면에 추가’를 선택하세요.</p>}
    </aside>
  );
}

declare global {
  interface Navigator {
    standalone?: boolean;
  }
}
