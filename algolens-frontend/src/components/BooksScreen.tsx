import { useCallback, useEffect, useState } from 'react';
import { BookPlus, Plus, Trash2, X } from 'lucide-react';

import { useTheme } from '../adapters/react/ThemeContext';
import { isValidPortfolioId, normalizePortfolioId } from '../domain/portfolio/portfolioAssignment';
import { PortfolioApiService, type Book } from '../infrastructure/api/portfolioApi';
import { RemoveFromBookModal } from './RemoveFromBookModal';

type RemoveTarget = { strategyId: string; strategyName: string; portfolioId: string };

/**
 * Define the books, and decide what goes in each.
 *
 * A book is a portfolio. Declared books can exist empty, so you can set one up
 * and then decide what belongs in it; books already in use appear too, marked
 * "undeclared".
 *
 * A strategy can be in several books at once. The read side always supported
 * this — positions, equity and results are keyed on (strategy, portfolio) pairs
 * — so a strategy in two books simply produces two independent sets of rows.
 *
 * Adding is free and inline. Removing goes through a modal, because it makes
 * that one book history discontinuous.
 */
export function BooksScreen() {
  const { theme } = useTheme();
  const [books, setBooks] = useState<Book[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [removing, setRemoving] = useState<RemoveTarget | null>(null);
  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [addStrategyId, setAddStrategyId] = useState('');
  const [addReason, setAddReason] = useState('');

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

  // Every distinct strategy across every book, so one can be added to a book it
  // is not in yet. There is no endpoint listing strategies independent of their
  // books, and deriving it here keeps this screen to one round trip.
  const allStrategies = new Map<string, { id: string; name: string }>();
  (books ?? []).forEach(b => b.strategies.forEach(st => allStrategies.set(st.id, st)));

  function beginAdd(portfolioId: string) {
    setAddingTo(portfolioId);
    setAddStrategyId('');
    setAddReason('');
  }

  async function handleAdd(book: Book) {
    setNotice(null);
    const result = await PortfolioApiService.addStrategyToBook({
      portfolio_id: book.portfolio_id,
      strategy_id: addStrategyId,
      reason: addReason.trim(),
    });
    if (result.outcome === 'rejected') {
      setError(result.message);
      return;
    }
    setAddingTo(null);
    setError(null);
    await load();
  }

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

              {book.strategies.length === 0 && (
                <div className={`px-4 py-6 text-center text-sm ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                  Empty — add a strategy below.
                </div>
              )}
              {book.strategies.length > 0 && (
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
                    <div className="flex items-center gap-3">
                      {strategy.is_primary && (
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                            isDark ? 'bg-gray-800 text-gray-400' : 'bg-gray-200 text-gray-600'
                          }`}
                          title="The book the engine reads where a single answer is needed"
                        >
                          primary
                        </span>
                      )}
                      <button
                        aria-label={`Remove ${strategy.name} from ${book.portfolio_id}`}
                        onClick={() =>
                          setRemoving({
                            strategyId: strategy.id,
                            strategyName: strategy.name,
                            portfolioId: book.portfolio_id,
                          })
                        }
                        className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs ${
                          isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
                        }`}
                      >
                        <X className="w-3.5 h-3.5" />
                        Remove
                      </button>
                    </div>
                  </div>
                ))
              )}

              {/* Adding takes nothing away from the books a strategy is already
                  in, so it needs no confirmation step. */}
              <div className={`px-4 py-3 border-t ${isDark ? 'border-gray-800' : 'border-gray-200'}`}>
                {addingTo === book.portfolio_id ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      autoFocus
                      aria-label={`Add a strategy to ${book.portfolio_id}`}
                      value={addStrategyId}
                      onChange={e => setAddStrategyId(e.target.value)}
                      className={`rounded-lg border px-2 py-1.5 text-sm ${
                        isDark ? 'bg-gray-900 border-gray-700 text-white' : 'bg-white border-gray-300'
                      }`}
                    >
                      <option value="" disabled>Choose a strategy...</option>
                      {[...allStrategies.values()]
                        .filter(st => !book.strategies.some(existing => existing.id === st.id))
                        .map(st => <option key={st.id} value={st.id}>{st.name}</option>)}
                    </select>
                    {/* Required, exactly as it is for removal. Adding takes
                        nothing away, so it needs no acknowledgement -- but it
                        still changes what a book holds, and the audit row is
                        worthless without a stated reason. */}
                    <input
                      aria-label={`Reason for adding to ${book.portfolio_id}`}
                      value={addReason}
                      onChange={e => setAddReason(e.target.value)}
                      placeholder="Reason (required)"
                      className={`flex-1 min-w-[200px] rounded-lg border px-2 py-1.5 text-sm ${
                        isDark
                          ? 'bg-gray-900 border-gray-700 text-white placeholder-gray-500'
                          : 'bg-white border-gray-300 placeholder-gray-400'
                      }`}
                    />
                    <button
                      onClick={() => handleAdd(book)}
                      disabled={!addStrategyId || addReason.trim() === ''}
                      className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40"
                    >
                      Add
                    </button>
                    <button
                      onClick={() => setAddingTo(null)}
                      className={`rounded-lg px-2.5 py-1.5 text-xs ${
                        isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
                      }`}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => beginAdd(book.portfolio_id)}
                    className={`inline-flex items-center gap-1.5 text-xs ${
                      isDark ? 'text-gray-400 hover:text-white' : 'text-gray-500 hover:text-black'
                    }`}
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add a strategy
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {removing && (
        <RemoveFromBookModal
          strategyId={removing.strategyId}
          strategyName={removing.strategyName}
          portfolioId={removing.portfolioId}
          theme={theme}
          onClose={() => setRemoving(null)}
          onRemoved={() => {
            setRemoving(null);
            void load();
          }}
        />
      )}
    </div>
  );
}
