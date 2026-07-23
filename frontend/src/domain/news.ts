import { z } from "zod";

import {
  httpUrlSchema,
  identifierSchema,
  symbolSchema,
  utcIsoStringSchema,
} from "./primitives";

export const newsItemSchema = z.object({
  id: identifierSchema,
  title: z.string().trim().min(1),
  summary: z.string(),
  source: z.string().trim().min(1),
  sourceUrl: httpUrlSchema,
  publishedAt: utcIsoStringSchema,
  fetchedAt: utcIsoStringSchema,
  symbols: z.array(symbolSchema).min(1),
});

export type NewsItem = z.infer<typeof newsItemSchema>;
