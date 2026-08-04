import {
  paperAccountCreateSchema,
  type PaperAccountCreate,
} from "../../domain/paper-trading";

export interface PaperAccountFormValues {
  initialCash: string;
}

export const defaultPaperAccountFormValues: PaperAccountFormValues = {
  initialCash: "10000",
};

type PaperAccountFormParseResult =
  | { input: PaperAccountCreate; message: null }
  | { input: null; message: string };

export function parsePaperAccountForm(
  values: PaperAccountFormValues,
): PaperAccountFormParseResult {
  const parsed = paperAccountCreateSchema.safeParse({
    initialCash: values.initialCash.trim(),
  });
  if (!parsed.success) {
    return {
      input: null,
      message: "初始资金必须是大于 0 的十进制数字。",
    };
  }
  return { input: parsed.data, message: null };
}
