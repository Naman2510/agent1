/** A failed request, in the backend's error envelope: `{"error": {code, message, ...}}`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields: string[] = [],
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string; fields?: string[]; request_id?: string | null };
}

export async function toApiError(response: Response): Promise<ApiError> {
  let envelope: ErrorEnvelope = {};
  try {
    envelope = (await response.json()) as ErrorEnvelope;
  } catch {
    // A proxy's HTML error page, or an empty body: the status is all there is.
  }
  const error = envelope.error ?? {};
  return new ApiError(
    response.status,
    error.code ?? "http_error",
    error.message ?? `Request failed (${response.status}).`,
    error.fields ?? [],
    error.request_id ?? null,
  );
}

/** Words a student can act on, keyed by the backend's stable error codes. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Could not reach VaaniOS. Check your connection and try again.";
  }
  switch (error.code) {
    case "invalid_credentials":
      return "That email and password don't match.";
    case "conflict":
      return "An account with that email already exists.";
    case "rate_limited":
      return "Too many attempts. Wait a minute and try again.";
    case "validation_error":
      return error.fields.length
        ? `Please check: ${error.fields.join(", ")}.`
        : "Some details are missing or invalid.";
    default:
      return error.message;
  }
}
