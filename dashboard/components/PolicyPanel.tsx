'use client';

import { Shield, RefreshCw, Check } from 'lucide-react';

interface PolicyConfig {
  max_experience_years: number;
  min_salary_annual: number;
  min_salary_hourly: number;
  enforce_visa_sponsorship: boolean;
  enforce_no_clearance: boolean;
  custom_red_flag_keywords: string[];
}

interface PolicyPanelProps {
  policyLoading: boolean;
  policyConfig: PolicyConfig | null;
  setPolicyConfig: (val: PolicyConfig | null | ((prev: PolicyConfig | null) => PolicyConfig | null)) => void;
  savePolicyConfig: (updated: PolicyConfig) => void;
}

export default function PolicyPanel({
  policyLoading,
  policyConfig,
  setPolicyConfig,
  savePolicyConfig,
}: PolicyPanelProps) {
  return (
    <div className="bg-slate-900/20 backdrop-blur-md border border-slate-800 p-6 rounded-2xl space-y-6 max-w-3xl shadow-xl">
      {policyLoading || !policyConfig ? (
        <div className="flex-1 flex flex-col items-center justify-center p-12 text-center border border-slate-800 rounded-2xl bg-slate-900/10">
          <RefreshCw className="w-10 h-10 text-violet-500 animate-spin mb-3" />
          <p className="text-sm text-slate-400 font-medium">Loading classifier policy guidelines...</p>
        </div>
      ) : (
        <div className="space-y-6 animate-in fade-in duration-300">
          <div className="flex items-center justify-between pb-4 border-b border-slate-800">
            <div className="flex items-center space-x-2">
              <Shield className="w-5 h-5 text-violet-400" />
              <h2 className="text-lg font-bold text-white">Classifier Policy & Experience Rules</h2>
            </div>
            <span className="text-[10px] bg-violet-950/60 text-violet-400 px-2 py-0.5 rounded border border-violet-850 font-bold uppercase tracking-wider">
              Gemini Policy Gating
            </span>
          </div>

          {/* Max Experience Input */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                Max Allowed Experience Cap
              </label>
              <span className="text-xs font-bold text-violet-400">
                {policyConfig.max_experience_years} Years
              </span>
            </div>
            <div className="flex items-center space-x-4">
              <input
                type="range"
                min="3"
                max="15"
                value={policyConfig.max_experience_years}
                onChange={(e) =>
                  setPolicyConfig({
                    ...policyConfig,
                    max_experience_years: Number(e.target.value),
                  })
                }
                className="flex-1 accent-violet-600 bg-slate-950 h-2 rounded-lg appearance-none cursor-pointer"
              />
              <input
                type="number"
                min="3"
                max="15"
                value={policyConfig.max_experience_years}
                onChange={(e) =>
                  setPolicyConfig({
                    ...policyConfig,
                    max_experience_years: Number(e.target.value),
                  })
                }
                className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-2 py-1.5 text-center text-xs text-slate-200 focus:outline-none focus:border-violet-600/70"
              />
            </div>
            <p className="text-[10px] text-slate-500">
              Jobs requesting experience years at or above this threshold will be flagged as R2 and automatically rejected.
            </p>
          </div>

          {/* Salary Threshold inputs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 pt-4 border-t border-slate-800">
            <div className="space-y-2">
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                Min Annual Salary
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500 text-xs">
                  $
                </span>
                <input
                  type="number"
                  value={policyConfig.min_salary_annual}
                  onChange={(e) =>
                    setPolicyConfig({
                      ...policyConfig,
                      min_salary_annual: Number(e.target.value),
                    })
                  }
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-6 pr-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 shadow-inner"
                />
              </div>
              <p className="text-[10px] text-slate-500">
                Block salaried positions offering below this annual rate (e.g. $80,000).
              </p>
            </div>

            <div className="space-y-2">
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                Min Hourly Rate
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500 text-xs">
                  $
                </span>
                <input
                  type="number"
                  value={policyConfig.min_salary_hourly}
                  onChange={(e) =>
                    setPolicyConfig({
                      ...policyConfig,
                      min_salary_hourly: Number(e.target.value),
                    })
                  }
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-6 pr-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 shadow-inner"
                />
              </div>
              <p className="text-[10px] text-slate-500">
                Block hourly contracts offering at or below this hourly rate (e.g. $50/hr).
              </p>
            </div>
          </div>

          {/* Checkbox Gating Rules */}
          <div className="space-y-3 pt-4 border-t border-slate-800">
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
              Standard Security Restrictions
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Visa sponsorship toggle */}
              <label className="flex items-center space-x-3 bg-slate-950/40 p-3 rounded-xl border border-slate-800 cursor-pointer hover:border-slate-700 transition-colors">
                <input
                  type="checkbox"
                  checked={policyConfig.enforce_visa_sponsorship}
                  onChange={(e) =>
                    setPolicyConfig({
                      ...policyConfig,
                      enforce_visa_sponsorship: e.target.checked,
                    })
                  }
                  className="w-4 h-4 text-violet-600 bg-slate-900 border-slate-800 rounded focus:ring-violet-600 focus:ring-offset-slate-900"
                />
                <div>
                  <span className="text-xs font-bold text-slate-200 block">
                    Block Visa Sponsorship Limits
                  </span>
                  <span className="text-[9px] text-slate-500 block mt-0.5">
                    {'Reject jobs that explicitly state "no sponsorship" or "cannot sponsor"'}
                  </span>
                </div>
              </label>

              {/* Security clearance toggle */}
              <label className="flex items-center space-x-3 bg-slate-950/40 p-3 rounded-xl border border-slate-800 cursor-pointer hover:border-slate-700 transition-colors">
                <input
                  type="checkbox"
                  checked={policyConfig.enforce_no_clearance}
                  onChange={(e) =>
                    setPolicyConfig({
                      ...policyConfig,
                      enforce_no_clearance: e.target.checked,
                    })
                  }
                  className="w-4 h-4 text-violet-600 bg-slate-900 border-slate-800 rounded focus:ring-violet-600 focus:ring-offset-slate-900"
                />
                <div>
                  <span className="text-xs font-bold text-slate-200 block">
                    Block Security Clearance Roles
                  </span>
                  <span className="text-[9px] text-slate-500 block mt-0.5">
                    {'Reject roles requesting "Active Secret/TS Clearance" or government eligibility'}
                  </span>
                </div>
              </label>
            </div>
          </div>

          {/* Custom Red Flag Keywords */}
          <div className="space-y-2 pt-4 border-t border-slate-800">
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
              Custom Red Flag Keywords (Comma separated)
            </label>
            <input
              type="text"
              placeholder="clearance, visa limit, federal, internship"
              value={policyConfig.custom_red_flag_keywords.join(', ')}
              onChange={(e) =>
                setPolicyConfig({
                  ...policyConfig,
                  custom_red_flag_keywords: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter((s) => s),
                })
              }
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder-slate-650 focus:outline-none focus:border-violet-600/70 shadow-inner"
            />
            <p className="text-[10px] text-slate-500">
              Any exact keyword or phrase match will instantly flag the job as rejected.
            </p>
          </div>

          {/* Save panel */}
          <div className="pt-6 border-t border-slate-850 flex justify-end">
            <button
              onClick={() => savePolicyConfig(policyConfig)}
              className="inline-flex items-center px-6 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-sm font-semibold shadow-md shadow-violet-500/10 border border-violet-500/20 active:scale-95 transition-all"
            >
              <Check className="w-4 h-4 mr-2" />
              Apply Policy Rules
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
