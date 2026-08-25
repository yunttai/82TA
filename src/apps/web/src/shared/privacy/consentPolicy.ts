import {
  getCurrentSession,
  listConsents,
  type ConsentRecord,
  type ConsentType,
} from "../api/publicService";

export function privacyDocumentVersion(): string | null {
  const value = import.meta.env.VITE_PRIVACY_DOCUMENT_VERSION;
  return value === undefined || value.trim().length === 0 ? null : value.trim();
}

export function hasCurrentConsent(
  records: readonly ConsentRecord[],
  consentType: ConsentType,
  documentVersion = privacyDocumentVersion(),
): boolean {
  if (documentVersion === null) return false;
  return records.some((record) => record.consentType === consentType
    && record.accepted
    && record.documentVersion === documentVersion);
}

export async function loadCurrentUserConsents(): Promise<ConsentRecord[] | null> {
  const session = await getCurrentSession();
  if (!session.response.ok || session.data?.subjectType !== "USER") return null;
  const consents = await listConsents();
  return consents.response.ok && consents.data !== undefined ? consents.data.items : null;
}

export async function checkCurrentConsent(consentType: ConsentType): Promise<boolean> {
  try {
    const records = await loadCurrentUserConsents();
    return records !== null && hasCurrentConsent(records, consentType);
  } catch {
    return false;
  }
}
