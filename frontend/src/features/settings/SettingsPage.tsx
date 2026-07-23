import { useState, type FormEvent } from "react";

import {
  loadPreferences,
  savePreferences,
  type Preferences,
} from "./preferences-store";

export function SettingsPage() {
  const [preferences, setPreferences] =
    useState<Preferences>(loadPreferences);
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
    setPreferences(savePreferences(preferences));
    setSaved(true);
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
              updatePreference(
                "theme",
                event.target.value as Preferences["theme"],
              );
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
              updatePreference("displayTimezone", event.target.value);
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
              updatePreference(
                "refreshPreference",
                event.target.value as Preferences["refreshPreference"],
              );
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
      </form>
    </section>
  );
}
