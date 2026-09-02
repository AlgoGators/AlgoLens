import { useCallback, useEffect, useState } from 'react';
import { ArrowRightLeft, BookPlus, Trash2 } from 'lucide-react';

import { useTheme } from '../adapters/react/ThemeContext';
import { isValidPortfolioId, normalizePortfolioId } from '../domain/portfolio/portfolioAssignment';
import { PortfolioApiService, type Book } from '../infrastructure/api/portfolioApi';
import { ReassignPortfolioModal } from './ReassignPortfolioModal';

type MoveTarget = { strategyId: string; strategyName: string; portfolioId: string };

/**
 * Define the books, and decide what goes in each.
 *
 * A book is a portfolio. Until now one existed only as a distinct portfolio_id
 * on the strategy registry, so an empty book could not exist — you could not
 * set one up and then decide what belongs in it. Declared books make that
 * possible; books already in use still appear, marked as such.
 */
export function BooksScreen() {
  const { theme } = useTheme();
  const [books, setBooks] = useState<Book[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [moving, setMoving] = useState<MoveTarget | null>(null);

  const [newId, setNewId] = useState('');
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [creating, setCreating] = useState(false);

  const isDark = theme === 'dark';

  const load = useCallback(async () => {
    try {
      setBooks(await PortfolioApiService.getBooks());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load books');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleCreate() {
    setCreating(true);
    setNotice(null);
    try {
      const result = await PortfolioApiService.createBook({
        portfolio_id: normalizePortfolioId(newId),
        name: newName.trim(),
        description: newDescription.trim(),
      });
      if (result.outcome === 'rejected') {
        setError(result.message);
        return;
      }
      setNewId('');
      setNewName('');
      setNewDescription('');
      setError(null);
      setNotice(`${result.book.portfolio_id} is ready. Move strategies into it below.`);
      await load();
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(book: Book) {
    setNotice(null);
    const result = await PortfolioApiService.deleteBook(book.portfolio_id);
    if (result.outcome === 'rejected') {
      setError(result.message);
      return;
    }
    setError(null);
    await load();
  }

  const inputClass = `w-full px-3 py-2 rounded-lg border text-sm ${
    isDark
      ? 'bg-gray-900 border-gray-700 text-white placeholder-gray-500'
      : 'bg-white border-gray-300 text-black placeholder-gray-400'
  }`;
  const labelClass = `block text-xs font-medium mb-1 ${isDark ? 'text-gray-400' : 'text-gray-500'}`;

  const idIsValid = newId.trim() === '' || isValidPortfolioId(newId);
  const allIds = (books ?? []).map(b => b.portfolio_id);

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      <div>
        <h1 className="text-2xl mb-1">Books</h1>
        <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
          A book is a portfolio the engine trades and reports on separately. Define one
          here, then decide which strategies belong in it.
        </p>
      </div>

      {/* Create */}
      <div className={`rounded-lg border p-5 ${isDark ? 'border-gray-800' : 'border-gray-200'}`}>
        <div className="flex items-center gap-2 mb-4">
          <BookPlus className="w-4 h-4" />
          <h2 className="text-sm uppercase tracking-wider">New book</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <label className={labelClass} htmlFor="book-id">Identifier</label>
            <input
              id="book-id"
              className={inputClass}
              value={newId}
              onChange={e => setNewId(e.target.value)}
              placeholder="MACRO_BOOK"
            />
            <p className={`mt-1 text-xs ${idIsValid ? (isDark ? 'text-gray-500' : 'text-gray-400') : 'text-red-500'}`}>
              {idIsValid
                ? 'Letters, digits, underscores and hyphens. Used by the engine.'
                : 'Only letters, digits, underscores and hyphens.'}
            </p>
          </div>
          <div>
            <label className={labelClass} htmlFor="book-name">Name (optional)</label>
            <input
              id="book-name"
              className={inputClass}
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="Macro Book"
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="book-desc">Description (optional)</label>
            <input
              id="book-desc"
              className={inputClass}
              value={newDescription}
              onChange={e => setNewDescription(e.target.value)}
              placeholder="Global macro and trend"
            />
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={handleCreate}
            disabled={creating || !isValidPortfolioId(newId)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-40"
          >
            {creating ? 'Creating…' : 'Create book'}
          </button>
          {notice && (
            <span className={`text-sm ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
              {notice}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Books */}
      {!books ? (
        <div className={`text-sm ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>Loading…</div>
      ) : (
        <div className="space-y-4">
          {books.map(book => (
            <div
              key={book.portfolio_id}
              className={`rounded-lg border overflow-hidden ${isDark ? 'border-gray-800' : 'border-gray-200'}`}
            >
              <div
                className={`flex items-start justify-between px-4 py-3 border-b ${
                  isDark ? 'bg-gray-900 border-gray-800' : 'bg-gray-50 border-gray-200'
                }`}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{book.name}</span>
                    <span className={`font-mono text-xs ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                      {book.portfolio_id}
                    </span>
                    {!book.declared && (
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                          isDark ? 'bg-gray-800 text-gray-400' : 'bg-gray-200 text-gray-600'
                        }`}
                        title="In use by a strategy but never formally defined here"
                      >
                        undeclared
                      </span>
                    )}
                  </div>
                  {book.description && (
                    <p className={`mt-1 text-xs ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
                      {book.description}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-xs ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                    {book.strategy_count}{' '}
                    {book.strategy_count === 1 ? 'strategy' : 'strategies'}
                  </span>
                  {/* Only an empty book can be removed; the server enforces it too. */}
                  {book.strategy_count === 0 && (
                    <button
                      aria-label={`Delete ${book.portfolio_id}`}
                      onClick={() => handleDelete(book)}
                      className={`rounded-lg p-1.5 ${isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'}`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>

              {book.strategies.length === 0 ? (
                <div className={`px-4 py-6 text-center text-sm ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                  Empty — move a strategy here from another book.
                </div>
              ) : (
                book.strategies.map(strategy => (
                  <div
                    key={strategy.id}
                    className={`flex items-center justify-between px-4 py-3 border-b last:border-b-0 ${
                      isDark ? 'border-gray-800 hover:bg-gray-900' : 'border-gray-100 hover:bg-gray-50'
                    }`}
                  >
                    <div>
                      <div className="text-sm">{strategy.name}</div>
                      <div className={`text-xs font-mono ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                        {strategy.strategy_type}
                        {strategy.lifecycle !== 'live' && (
                          <span className="ml-2 uppercase">· {strategy.lifecycle}</span>
                        )}
                      </div>
                    </div>
                    <button
                      aria-label={`Move ${strategy.name} to another book`}
                      onClick={() =>
                        setMoving({
                          strategyId: strategy.id,
                          strategyName: strategy.name,
                          portfolioId: book.portfolio_id,
                        })
                      }
                      className={`inline-flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs ${
                        isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
                      }`}
                    >
                      <ArrowRightLeft className="w-4 h-4" />
                      Move
                    </button>
                  </div>
                ))
              )}
            </div>
          ))}
        </div>
      )}

      {moving && (
        <ReassignPortfolioModal
          strategyId={moving.strategyId}
          strategyName={moving.strategyName}
          currentPortfolioId={moving.portfolioId}
          knownPortfolioIds={allIds}
          theme={theme}
          onClose={() => setMoving(null)}
          onSaved={() => {
            setMoving(null);
            void load();
          }}
        />
      )}
    </div>
  );
}
