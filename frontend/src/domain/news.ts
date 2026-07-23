import { z } from "zod";

import {
  identifierSchema,
  symbolSchema,
  utcIsoStringSchema,
} from "./primitives";

export const newsItemSchema = z.object({
  id: identifierSchema,
  title: z.string().trim().min(1),
  summary: z.string(),
  source: z.string().trim().min(1),
  sourceUrl: z.url(),
  publishedAt: utcIsoStringSchema,
  fetchedAt: utcIsoStringSchema,
  symbols: z.array(symbolSchema).min(1),
});

export type NewsItem = z.infer<typeof newsItemSchema>;
