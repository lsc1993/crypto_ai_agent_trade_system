export const MOCK_STORAGE_KEY = "crypto-workbench:mock-state:v1";

export function resetMockWorkbench(): void {
  if (typeof localStorage !== "undefined") {
    localStorage.removeItem(MOCK_STORAGE_KEY);
  }
}
