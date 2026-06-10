'use client';

import { Settings as SettingsIcon, Check } from 'lucide-react';

interface SettingsPanelProps {
  webhookUrlInput: string;
  setWebhookUrlInput: (val: string) => void;
  testWebhook: () => void;
  testingWebhook: boolean;
  sendDigestOnly: boolean;
  setSendDigestOnly: (val: boolean) => void;
  titlesInput: string;
  setTitlesInput: (val: string) => void;
  schedulerEnabled: boolean;
  setSchedulerEnabled: (val: boolean) => void;
  schedulerHour: number;
  setSchedulerHour: (val: number) => void;
  schedulerMinute: number;
  setSchedulerMinute: (val: number) => void;
  saveSettings: () => void;
  onResetTargetTitles?: () => void;
  resettingTitles?: boolean;
  joobleApiKeyInput: string;
  setJoobleApiKeyInput: (val: string) => void;
}

export default function SettingsPanel({
  webhookUrlInput,
  setWebhookUrlInput,
  testWebhook,
  testingWebhook,
  sendDigestOnly,
  setSendDigestOnly,
  titlesInput,
  setTitlesInput,
  schedulerEnabled,
  setSchedulerEnabled,
  schedulerHour,
  setSchedulerHour,
  schedulerMinute,
  setSchedulerMinute,
  saveSettings,
  onResetTargetTitles,
  resettingTitles,
  joobleApiKeyInput,
  setJoobleApiKeyInput,
}: SettingsPanelProps) {
  return (
    <div className="bg-slate-900/20 backdrop-blur-md border border-slate-850 p-6 rounded-2xl space-y-6 max-w-3xl shadow-xl">
      <div className="flex items-center space-x-2 pb-4 border-b border-slate-800">
        <SettingsIcon className="w-5 h-5 text-violet-400" />
        <h2 className="text-lg font-bold text-white">Sourcing & Webhook Settings</h2>
      </div>

      {/* Webhook URLs */}
      <div className="space-y-3">
        <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
          Discord Notification Webhook
        </label>
        <div className="flex space-x-3">
          <input
            type="text"
            placeholder="https://discord.com/api/webhooks/..."
            value={webhookUrlInput}
            onChange={(e) => setWebhookUrlInput(e.target.value)}
            className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-violet-600/70 shadow-inner"
          />
          <button
            onClick={testWebhook}
            disabled={testingWebhook}
            className="inline-flex items-center px-4 py-2 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-colors"
          >
            {testingWebhook ? 'Testing...' : 'Test Webhook'}
          </button>
        </div>

        {/* Webhook Delivery Preference Toggle */}
        <div className="bg-slate-950/40 border border-slate-850 p-3 rounded-xl flex items-center justify-between">
          <div className="space-y-0.5">
            <span className="text-xs font-bold text-slate-300">Delivery Preference</span>
            <p className="text-[11px] text-slate-500">
              Consolidated digest groups all new approved jobs into a single summary card instead of individual alerts.
            </p>
          </div>
          <label className="inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={sendDigestOnly}
              onChange={(e) => setSendDigestOnly(e.target.checked)}
              className="sr-only peer"
            />
            <div className="relative w-9 h-5 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-violet-600 peer-checked:after:bg-white"></div>
            <span className="ms-2 text-xs font-semibold text-slate-300">Digest</span>
          </label>
        </div>

        <p className="text-xs text-slate-500">Sends alerts when new approved jobs are synced to Notion.</p>
      </div>

      {/* Target titles */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
            Target Job Titles Sourcing List (One per line)
          </label>
          {onResetTargetTitles && (
            <button
              type="button"
              onClick={onResetTargetTitles}
              disabled={resettingTitles}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 text-slate-300 hover:text-white hover:border-violet-600/50 transition-colors disabled:opacity-50"
            >
              {resettingTitles ? 'Restoring…' : 'Restore defaults'}
            </button>
          )}
        </div>
        <textarea
          rows={8}
          placeholder="DevOps Engineer&#10;Platform Engineer"
          value={titlesInput}
          onChange={(e) => setTitlesInput(e.target.value)}
          className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-violet-600/70 shadow-inner"
        />
      </div>

      {/* Scheduler Settings */}
      <div className="space-y-4 pt-4 border-t border-slate-850">
        <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
          Background Scheduler Configuration
        </label>
        <div className="flex flex-col sm:flex-row sm:items-center gap-6">
          <label className="inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={schedulerEnabled}
              onChange={(e) => setSchedulerEnabled(e.target.checked)}
              className="sr-only peer"
            />
            <div className="relative w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-violet-600 peer-checked:after:bg-white"></div>
            <span className="ms-3 text-sm font-medium text-slate-300">Run automatically every day</span>
          </label>

          {schedulerEnabled && (
            <div className="flex items-center space-x-2">
              <span className="text-sm text-slate-400">at</span>
              <input
                type="number"
                min="0"
                max="23"
                value={schedulerHour}
                onChange={(e) => setSchedulerHour(Number(e.target.value))}
                className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-center text-sm text-slate-200 focus:outline-none focus:border-violet-600/70"
              />
              <span className="text-sm text-slate-400">:</span>
              <input
                type="number"
                min="0"
                max="59"
                value={schedulerMinute}
                onChange={(e) => setSchedulerMinute(Number(e.target.value))}
                className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-center text-sm text-slate-200 focus:outline-none focus:border-violet-600/70"
              />
            </div>
          )}
        </div>
      </div>

      {/* Active Sourcing Channels */}
      <div className="space-y-4 pt-4 border-t border-slate-850">
        <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
          Active Sourcing Channels & Intelligence
        </label>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-slate-950/40 border border-slate-850 p-4 rounded-xl space-y-2">
            <div className="flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="text-xs font-bold text-slate-200">LinkedIn Guest Finder</span>
            </div>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Stealthily crawls LinkedIn's public guest listings for your target job titles in the US. Runs out-of-the-box.
            </p>
          </div>
          <div className="bg-slate-950/40 border border-slate-850 p-4 rounded-xl space-y-2">
            <div className="flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="text-xs font-bold text-slate-200">HN Startup Sourcing</span>
            </div>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Scrapes the monthly Ask HN: Who is hiring? threads to discover remote startup roles. Runs out-of-the-box.
            </p>
          </div>
          <div className="bg-slate-950/40 border border-slate-850 p-4 rounded-xl space-y-2 col-span-1 md:col-span-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <span className={`w-2 h-2 rounded-full ${joobleApiKeyInput ? 'bg-emerald-500 animate-pulse' : 'bg-violet-500'}`}></span>
                <span className="text-xs font-bold text-slate-200">Jooble Aggregator API</span>
              </div>
              <a
                href="https://jooble.org/api/about"
                target="_blank"
                rel="noreferrer"
                className="text-[10px] text-violet-400 hover:text-violet-300 transition-colors hover:underline"
              >
                Get free API Key
              </a>
            </div>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Enter your Jooble API key to aggregate listings from thousands of other job boards. You can also configure it as <code className="text-violet-400 font-mono text-[10px]">JOOBLE_API_KEY</code> in your <code className="text-slate-400 font-mono text-[10px]">.env</code> file.
            </p>
            <input
              type="password"
              placeholder="Paste your Jooble API Key here..."
              value={joobleApiKeyInput}
              onChange={(e) => setJoobleApiKeyInput(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-violet-600/70 shadow-inner transition-colors"
            />
          </div>
        </div>
      </div>

      {/* Submit panel */}
      <div className="pt-6 border-t border-slate-800 flex justify-end">
        <button
          onClick={saveSettings}
          className="inline-flex items-center px-6 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-sm font-semibold shadow-md shadow-violet-500/10 border border-violet-500/20 active:scale-95 transition-all"
        >
          <Check className="w-4 h-4 mr-2" />
          Save Settings
        </button>
      </div>
    </div>
  );
}
