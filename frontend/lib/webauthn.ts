/** Pont entre l'API WebAuthn du navigateur et le format JSON de notre serveur. */

export function b64urlToBuffer(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64 + "=".repeat((4 - (base64.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

export function bufferToB64url(buffer: ArrayBuffer): string {
  let binary = "";
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface DescriptorJSON {
  id: string;
  type: string;
  transports?: string[];
}

export interface CreationOptionsJSON {
  rp: { id: string; name: string };
  user: { id: string; name: string; displayName: string };
  challenge: string;
  pubKeyCredParams: { type: string; alg: number }[];
  timeout?: number;
  excludeCredentials?: DescriptorJSON[];
  authenticatorSelection?: Record<string, unknown>;
  attestation?: string;
}

export interface RequestOptionsJSON {
  challenge: string;
  rpId?: string;
  timeout?: number;
  allowCredentials?: DescriptorJSON[];
  userVerification?: string;
}

/** Erreur dont le message est directement affichable à l'utilisateur. */
export class WebAuthnUserError extends Error {}

export function webauthnSupported(): boolean {
  return typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;
}

/** Vrai si l'appareil a un lecteur d'empreinte / Windows Hello utilisable. */
export async function platformAuthenticatorAvailable(): Promise<boolean> {
  if (!webauthnSupported()) return false;
  try {
    return await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}

function explain(error: unknown, action: "create" | "get"): WebAuthnUserError {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError")
    return new WebAuthnUserError("Opération annulée, refusée ou trop longue. Réessaie et pose ton doigt sur le lecteur quand Windows le demande.");
  if (name === "InvalidStateError")
    return new WebAuthnUserError(
      action === "create" ? "Une empreinte de cet appareil est déjà enregistrée pour cette personne." : "Aucune empreinte de cette personne n'est disponible sur cet appareil.",
    );
  if (name === "SecurityError")
    return new WebAuthnUserError("Adresse du site refusée par le navigateur. Ouvre le site avec http://localhost:3000 (et non 127.0.0.1).");
  if (name === "NotSupportedError") return new WebAuthnUserError("Cet appareil ne gère pas ce type de clé de sécurité.");
  if (name === "AbortError") return new WebAuthnUserError("Opération interrompue.");
  return new WebAuthnUserError("L'appareil n'a pas pu lire l'empreinte.");
}

/** Crée une clé liée à l'empreinte (ouvre la fenêtre Windows Hello). Renvoie le JSON à envoyer au serveur. */
export async function createCredential(options: CreationOptionsJSON) {
  const publicKey = {
    rp: options.rp,
    user: { id: b64urlToBuffer(options.user.id), name: options.user.name, displayName: options.user.displayName },
    challenge: b64urlToBuffer(options.challenge),
    pubKeyCredParams: options.pubKeyCredParams,
    timeout: options.timeout,
    excludeCredentials: options.excludeCredentials?.map((c) => ({
      type: "public-key",
      id: b64urlToBuffer(c.id),
      transports: c.transports,
    })),
    authenticatorSelection: options.authenticatorSelection,
    attestation: options.attestation,
  } as PublicKeyCredentialCreationOptions;

  let credential: PublicKeyCredential | null;
  try {
    credential = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  } catch (e) {
    throw explain(e, "create");
  }
  if (!credential) throw new WebAuthnUserError("Aucune clé n'a été créée.");
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: bufferToB64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      attestationObject: bufferToB64url(response.attestationObject),
      clientDataJSON: bufferToB64url(response.clientDataJSON),
      transports: response.getTransports?.() ?? [],
    },
  };
}

/** Demande à l'appareil de prouver l'identité par empreinte (ouvre la fenêtre Windows Hello). */
export async function getCredential(options: RequestOptionsJSON) {
  const publicKey = {
    challenge: b64urlToBuffer(options.challenge),
    rpId: options.rpId,
    timeout: options.timeout,
    userVerification: options.userVerification,
    allowCredentials: options.allowCredentials?.map((c) => ({
      type: "public-key",
      id: b64urlToBuffer(c.id),
      transports: c.transports,
    })),
  } as PublicKeyCredentialRequestOptions;

  let credential: PublicKeyCredential | null;
  try {
    credential = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  } catch (e) {
    throw explain(e, "get");
  }
  if (!credential) throw new WebAuthnUserError("Aucune empreinte n'a été lue.");
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: bufferToB64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      authenticatorData: bufferToB64url(response.authenticatorData),
      clientDataJSON: bufferToB64url(response.clientDataJSON),
      signature: bufferToB64url(response.signature),
      ...(response.userHandle ? { userHandle: bufferToB64url(response.userHandle) } : {}),
    },
  };
}
