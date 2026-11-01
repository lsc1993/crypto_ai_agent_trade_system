import { request } from "@playwright/test";

// Windows 子进程可能被直接终止，因此在 Playwright 关闭服务前回收本次 schema。
// 如果端口被其他进程占用，随机 token 会拒绝清理，不接触已有服务的数据。
export default async function globalTeardown(): Promise<void> {
  const baseURL = process.env.HTTP_E2E_BACKEND_URL;
  const token = process.env.HTTP_E2E_TOKEN;
  if (baseURL === undefined || token === undefined) {
    throw new Error("HTTP E2E cleanup configuration is missing");
  }
  const client = await request.newContext({ baseURL, timeout: 10_000 });
  try {
    const response = await client.post("/__http_e2e__/cleanup", {
      headers: { "x-http-e2e-token": token },
    });
    if (response.status() !== 204) {
      throw new Error("HTTP E2E owned schema cleanup failed");
    }
  } finally {
    await client.dispose();
  }
}
