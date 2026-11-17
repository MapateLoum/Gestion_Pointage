"use client";

// @ts-ignore React's types may be unavailable in the current TypeScript environment.
import { useCallback, useEffect, useRef, useState } from "react";

type WebcamState = "idle" | "starting" | "ready" | "error";

function describeError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Accès à la caméra refusé. Autorise-la dans le navigateur (icône de cadenas à côté de l'adresse), puis réessaie.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "Aucune caméra détectée sur cet appareil.";
  if (name === "NotReadableError") return "La caméra est utilisée par une autre application. Ferme-la puis réessaie.";
  return "Impossible de démarrer la caméra.";
}

/** Démarre la webcam tant que `active` est vrai et la coupe proprement ensuite. */
export function useWebcam(active: boolean, attempt = 0) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [state, setState] = useState<WebcamState>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setState("starting");
    setError(null);

    (async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("Ce navigateur ne peut pas utiliser la caméra (la page doit être en HTTPS ou sur localhost).");
        setState("error");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
        }
        setState("ready");
      } catch (e) {
        if (!cancelled) {
          setError(describeError(e));
          setState("error");
        }
      }
    })();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t: MediaStreamTrack) => t.stop()); // coupe le voyant de la caméra
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      setState("idle");
    };
  }, [active, attempt]);

  /** Image courante de la caméra, réduite, en JPEG (data URL). Non retournée en miroir. */
  const capture = useCallback((maxWidth = 800, quality = 0.85): string | null => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) return null;
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", quality);
  }, []);

  return { videoRef, state, error, capture };
}
