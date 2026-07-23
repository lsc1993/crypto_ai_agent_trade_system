import { z } from "zod";

import { httpUrlSchema, type Page } from "../../domain/primitives";

const errorEnvelopeSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.unknown().optional(),
});

export class WorkbenchHttpError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "WorkbenchHttpError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class WorkbenchResponseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WorkbenchResponseError";
  }
}

export interface HttpTransportOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
}

export function createWirePageSchema<T>(itemSchema: z.ZodType<T>) {
  return z
    .object({
      items: z.array(itemSchema),
      page: z.number().int().positive(),
      page_size: z.number().int().positive(),
      total: z.number().int().nonnegative(),
    })
    .transform(
      (wire): Page<T> => ({
        items: wire.items,
        page: wire.page,
        pageSize: wire.page_size,
        total: wire.total,
      }),
    );
}

export class HttpTransport {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpTransportOptions) {
    this.baseUrl = httpUrlSchema.parse(options.baseUrl);
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
  }

  async request<T>(
    path: string,
    schema: z.ZodType<T>,
    init: RequestInit = {},
  ): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    const response = await this.fetchImpl(new URL(path, this.baseUrl), {
      ...init,
      headers,
    });
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new WorkbenchResponseError(
        `HTTP response from ${path} was not valid JSON`,
      );
    }

    if (!response.ok) {
      const envelope = errorEnvelopeSchema.safeParse(body);
      if (!envelope.success) {
        throw new WorkbenchResponseError(
          `HTTP error response from ${path} did not match the error envelope`,
        );
      }
      throw new WorkbenchHttpError(
        response.status,
        envelope.data.code,
        envelope.data.message,
        envelope.data.details,
      );
    }

    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new WorkbenchResponseError(
        `HTTP response from ${path} did not match the workbench contract`,
      );
    }
    return parsed.data;
  }
}
