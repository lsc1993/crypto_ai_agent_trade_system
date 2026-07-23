import { useState, type FormEvent } from "react";

import {
  DEFAULT_PREFERENCES,
  loadPreferences,
  parseDisplayTimezone,
  parseRefreshPreference,
  parseThemePreference,
  savePreferences,
  type Preferences,
} from "./preferences-store";

type StorageFeedback = "read" | "write" | null;

function initializePreferences(): {
  preferences: Preferences;
  feedback: StorageFeedback;
} {
  try {
    return { preferences: loadPreferences(), feedback: null };
  } catch {
    return {
      preferences: { ...DEFAULT_PREFERENCES },
      feedback: "read",
    };
  }
}

export function SettingsPage() {
  const [initialState] = useState(initializePreferences);
  const [preferences, setPreferences] = useState<Preferences>(
    initialState.preferences,
  );
  const [storageFeedback, setStorageFeedback] =
    useState<StorageFeedback>(initialState.feedback);
  const [saved, setSaved] = useState(false);

  function updatePreference<Key extends keyof Preferences>(
    key: Key,
    value: Preferences[Key],
  ) {
    setPreferences((current) => ({ ...current, [key]: value }));
    setSaved(false);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setPreferences(savePreferences(preferences));
      setSaved(true);
      setStorageFeedback(null);
    } catch {
      setSaved(false);
      setStorageFeedback("write");
    }
  }

  return (
    <section className="research-page settings-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">本地显示偏好</p>
          <h1>设置</h1>
          <p>
            这里只保存主题、显示时区与刷新偏好，不保存账户、密钥、报告或交易草稿。
          </p>
        </div>
      </header>

      <form className="settings-form" onSubmit={handleSubmit}>
        <label>
          <span>主题</span>
          <select
            value={preferences.theme}
            onChange={(event) => {
              const theme = parseThemePreference(event.target.value);
              if (theme !== undefined) {
                updatePreference("theme", theme);
              }
            }}
          >
            <option value="system">跟随系统</option>
            <option value="dark">深色</option>
            <option value="light">浅色</option>
          </select>
        </label>

        <label>
          <span>显示时区</span>
          <select
            value={preferences.displayTimezone}
            onChange={(event) => {
              const timezone = parseDisplayTimezone(event.target.value);
              if (timezone !== undefined) {
                updatePreference("displayTimezone", timezone);
              }
            }}
          >
            <option value="UTC">UTC</option>
            <option value="Asia/Shanghai">Asia/Shanghai</option>
          </select>
        </label>

        <label>
          <span>刷新偏好</span>
          <select
            value={preferences.refreshPreference}
            onChange={(event) => {
              const refreshPreference = parseRefreshPreference(
                event.target.value,
              );
              if (refreshPreference !== undefined) {
                updatePreference(
                  "refreshPreference",
                  refreshPreference,
                );
              }
            }}
          >
            <option value="manual">仅手动刷新</option>
            <option value="auto">页面可见时自动刷新</option>
          </select>
        </label>

        <button className="primary-action" type="submit">
          保存显示偏好
        </button>
        {saved ? (
          <p className="settings-form__status" role="status">
            显示偏好已保存在当前浏览器。
          </p>
        ) : null}
        {storageFeedback === "read" ? (
          <p className="inline-error" role="alert">
            无法读取浏览器显示偏好，已使用安全默认值。
          </p>
        ) : null}
        {storageFeedback === "write" ? (
          <p className="inline-error" role="alert">
            无法保存显示偏好，请检查浏览器存储权限。
          </p>
        ) : null}
      </form>
    </section>
  );
}
