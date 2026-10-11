import React, { useEffect, useMemo, useState } from 'react';
import { Download, Search, Upload } from 'lucide-react';
import { useAuth } from '../../adapters/react/AuthContext';
import { useScreens } from '../../adapters/react/ScreenContext';
import { useTheme } from '../../adapters/react/ThemeContext';
import {
  InvestorService,
  ScreenService,
  type AdminUser,
} from '../../application/identity/screenService';
import {
  SCREEN_LABELS,
  SCREEN_ORDER,
  screensChanged,
  toggleScreen,
  type Screen,
} from '../../domain/identity/screens';
import {
  checkReportFile,
  formatBytes,
  REPORT_KINDS,
  reportKindLabel,
  type InvestorReport,
  type ReportKind,
} from '../../domain/investor/investor';
import { Card, SectionTitle } from '../ScreenFrame';

const SCREEN_HINTS: Record<Screen, string> = {
  member: 'Portfolios, strategies, incubation',
  investor: 'Published positions, reports and letters',
  qt: 'The QT desk: edit, override, approve',
};

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** One user's row: checkboxes for the three screens, saved with a confirmation. */
function UserRow({
  user,
  isSelf,
  onSaved,
}: {
  user: AdminUser;
  isSelf: boolean;
  onSaved: (user: AdminUser) => void;
}) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const [draft, setDraft] = useState<Screen[]>(user.screens);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = screensChanged(user.screens, draft);
  const name = [user.first_name, user.last_name].filter(Boolean).join(' ');

  useEffect(() => {
    setDraft(user.screens);
  }, [user.screens]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await ScreenService.setScreens(user.id, draft);
      onSaved({ ...user, screens: result.screens });
      setConfirming(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  };

  const button = (primary: boolean) =>
    `text-xs px-3 py-1.5 rounded transition-colors disabled:opacity-50 ${
      primary
        ? 'bg-orange-500 text-white hover:bg-orange-600'
        : dark
          ? 'text-gray-400 hover:text-white hover:bg-gray-800'
          : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
    }`;

  return (
    <div className={`p-4 border-b last:border-b-0 ${dark ? 'border-gray-800' : 'border-gray-200'}`}>
      <div className="flex flex-col md:flex-row md:items-center gap-3 md:gap-4">
        <div className="md:w-64 min-w-0">
          <div className="truncate">{user.email}</div>
          <div className={`text-sm ${dark ? 'text-gray-400' : 'text-gray-500'}`}>
            {name || '—'} · {user.role ?? 'no role'}
            {isSelf ? ' · you' : ''}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4 flex-1">
          {SCREEN_ORDER.map(screen => (
            <label key={screen} className="flex items-center gap-2 text-sm cursor-pointer" title={SCREEN_HINTS[screen]}>
              <input
                type="checkbox"
                className="accent-orange-500 w-4 h-4"
                checked={draft.includes(screen)}
                disabled={saving}
                onChange={e => {
                  setConfirming(false);
                  setDraft(current => toggleScreen(current, screen, e.target.checked));
                }}
              />
              {SCREEN_LABELS[screen]}
            </label>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {!confirming ? (
            <button type="button" className={button(true)} disabled={!changed || saving} onClick={() => setConfirming(true)}>
              Save
            </button>
          ) : (
            <>
              <span className="text-xs">
                {draft.length === 0 ? 'Remove all access?' : `Give ${draft.map(s => SCREEN_LABELS[s]).join(', ')}?`}
              </span>
              <button type="button" className={button(true)} disabled={saving} onClick={save}>
                {saving ? 'Saving...' : 'Confirm'}
              </button>
              <button type="button" className={button(false)} disabled={saving} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          )}
          {changed && !confirming && (
            <button type="button" className={button(false)} disabled={saving} onClick={() => setDraft(user.screens)}>
              Reset
            </button>
          )}
        </div>
      </div>
      {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
    </div>
  );
}

function UsersSection() {
  const { theme } = useTheme();
  const { user: me } = useAuth();
  const { reload: reloadMyScreens } = useScreens();
  const dark = theme === 'dark';
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    ScreenService.users()
      .then(setUsers)
      .catch(err => setError(errorText(err)));
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!users) return [];
    if (!q) return users;
    return users.filter(u =>
      [u.email, u.first_name, u.last_name, u.role].some(v => (v ?? '').toLowerCase().includes(q)),
    );
  }, [users, query]);

  const onSaved = (saved: AdminUser) => {
    setUsers(current => (current ? current.map(u => (u.id === saved.id ? saved : u)) : current));
    // An admin changing their own screens sees the switcher follow.
    if (String(saved.id) === String(me?.id)) reloadMyScreens();
  };

  return (
    <section>
      <SectionTitle>Screen access</SectionTitle>
      <p className={`text-sm mb-4 ${dark ? 'text-gray-400' : 'text-gray-500'}`}>
        Member: {SCREEN_HINTS.member}. Investor: {SCREEN_HINTS.investor}. QT: {SCREEN_HINTS.qt}. A
        change applies on the user's next request.
      </p>
      <div
        className={`flex items-center gap-2 mb-4 px-3 py-2 rounded-lg border ${
          dark ? 'border-gray-800 bg-gray-950' : 'border-gray-200 bg-white'
        }`}
      >
        <Search className={`w-4 h-4 ${dark ? 'text-gray-500' : 'text-gray-400'}`} />
        <input
          type="search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search by e-mail, name or role"
          className="flex-1 bg-transparent outline-none text-sm"
        />
      </div>
      {error ? (
        <p className="text-sm text-red-500">Could not load the users: {error}</p>
      ) : !users ? (
        <p className={dark ? 'text-gray-400' : 'text-gray-600'}>Loading users...</p>
      ) : shown.length === 0 ? (
        <p className={dark ? 'text-gray-400' : 'text-gray-600'}>No user matches.</p>
      ) : (
        <Card>
          {shown.map(u => (
            <UserRow key={u.id} user={u} isSelf={String(u.id) === String(me?.id)} onSaved={onSaved} />
          ))}
        </Card>
      )}
    </section>
  );
}

function ReportsSection() {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const [reports, setReports] = useState<InvestorReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState<ReportKind>('monthly');
  const [periodLabel, setPeriodLabel] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = () =>
    InvestorService.adminReports()
      .then(setReports)
      .catch(err => setError(errorText(err)));

  useEffect(() => {
    load();
  }, []);

  const upload = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!title.trim()) {
      setFormError('A title is required');
      return;
    }
    const problem = checkReportFile(file);
    if (problem || !file) {
      setFormError(problem ?? 'Choose a PDF file');
      return;
    }
    setUploading(true);
    try {
      const report = await InvestorService.uploadReport({ title: title.trim(), kind, periodLabel, file });
      setReports(current => [report, ...(current ?? [])]);
      setTitle('');
      setPeriodLabel('');
      setFile(null);
      setFileKey(k => k + 1);
    } catch (err) {
      setFormError(errorText(err));
    } finally {
      setUploading(false);
    }
  };

  const setPublished = async (report: InvestorReport, published: boolean) => {
    setBusy(report.id);
    setError(null);
    try {
      const updated = await InvestorService.updateReport(report.id, { published });
      setReports(current => (current ? current.map(r => (r.id === updated.id ? updated : r)) : current));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const download = async (report: InvestorReport) => {
    setBusy(report.id);
    setError(null);
    try {
      await InvestorService.adminDownloadReport(report);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const field = `w-full px-3 py-2 rounded-lg border text-sm bg-transparent ${
    dark ? 'border-gray-800' : 'border-gray-300'
  }`;
  const small = `text-xs px-3 py-1.5 rounded transition-colors disabled:opacity-50 ${
    dark ? 'text-gray-300 hover:bg-gray-800' : 'text-gray-600 hover:bg-gray-100'
  }`;

  return (
    <section>
      <SectionTitle>Investor reports and letters</SectionTitle>
      <Card className="p-4 mb-6">
        <form onSubmit={upload} className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="text-sm md:col-span-2">
            <span className={`block mb-1 ${muted}`}>Title</span>
            <input className={field} value={title} maxLength={200} onChange={e => setTitle(e.target.value)} placeholder="September 2026 report" />
          </label>
          <label className="text-sm">
            <span className={`block mb-1 ${muted}`}>Kind</span>
            <select
              className={`${field} ${dark ? 'bg-black' : 'bg-white'}`}
              value={kind}
              onChange={e => setKind(e.target.value as ReportKind)}
            >
              {REPORT_KINDS.map(k => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className={`block mb-1 ${muted}`}>Period (optional)</span>
            <input className={field} value={periodLabel} maxLength={40} onChange={e => setPeriodLabel(e.target.value)} placeholder="2026-09 or 2026 Q3" />
          </label>
          <label className="text-sm md:col-span-2">
            <span className={`block mb-1 ${muted}`}>PDF (up to 10 MB)</span>
            <input
              key={fileKey}
              type="file"
              accept="application/pdf,.pdf"
              className="text-sm"
              onChange={e => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <div className="md:col-span-2 flex items-center gap-3">
            <button
              type="submit"
              disabled={uploading}
              className="flex items-center gap-2 text-sm bg-orange-500 text-white px-4 py-2 rounded-lg hover:bg-orange-600 transition-colors disabled:opacity-60"
            >
              <Upload className="w-4 h-4" />
              {uploading ? 'Uploading...' : 'Upload and publish'}
            </button>
            {formError && <span className="text-sm text-red-500">{formError}</span>}
          </div>
        </form>
      </Card>

      {error && <p className="text-sm text-red-500 mb-3">{error}</p>}
      {!reports ? (
        <p className={muted}>Loading reports...</p>
      ) : reports.length === 0 ? (
        <p className={muted}>No reports uploaded yet.</p>
      ) : (
        <Card>
          {reports.map((report, index) => (
            <div
              key={report.id}
              className={`flex flex-col md:flex-row md:items-center justify-between gap-3 p-4 ${
                index !== reports.length - 1 ? `border-b ${dark ? 'border-gray-800' : 'border-gray-200'}` : ''
              }`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate">{report.title}</span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${
                      report.published
                        ? 'bg-orange-500 text-white'
                        : dark
                          ? 'bg-gray-800 text-gray-400'
                          : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {report.published ? 'Published' : 'Hidden'}
                  </span>
                </div>
                <div className={`text-sm ${muted}`}>
                  {reportKindLabel(report.kind)}
                  {report.period_label ? ` · ${report.period_label}` : ''} · {formatBytes(report.size_bytes)}
                  {report.uploaded_by ? ` · by ${report.uploaded_by}` : ''}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" className={`${small} flex items-center gap-1`} disabled={busy === report.id} onClick={() => download(report)}>
                  <Download className="w-3.5 h-3.5" /> PDF
                </button>
                <button
                  type="button"
                  className={small}
                  disabled={busy === report.id}
                  onClick={() => setPublished(report, !report.published)}
                >
                  {report.published ? 'Hide from investors' : 'Publish'}
                </button>
              </div>
            </div>
          ))}
        </Card>
      )}
    </section>
  );
}

/** The Admin screen (exec_board): assign screens, and manage investor reports. */
export function AdminHome() {
  const { theme } = useTheme();
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-2xl mb-1">Admin</h1>
        <p className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
          Assign each user the Member, Investor and QT screens, and publish investor reports.
        </p>
      </div>
      <UsersSection />
      <ReportsSection />
    </div>
  );
}
