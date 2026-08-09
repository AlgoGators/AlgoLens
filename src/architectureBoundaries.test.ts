import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const SRC_DIR = path.join(process.cwd(), 'src');

const IMPORT_RE =
  /import\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?['"]([^'"]+)['"]/g;

function sourceFiles(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];

  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return sourceFiles(fullPath);
    }
    return /\.(ts|tsx)$/.test(entry.name) ? [fullPath] : [];
  });
}

function importsFrom(filePath: string): string[] {
  const source = fs.readFileSync(filePath, 'utf8');
  return Array.from(source.matchAll(IMPORT_RE)).map(match => match[1]);
}

function rel(filePath: string): string {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

function resolvedRelativeImport(filePath: string, imported: string): string | null {
  if (!imported.startsWith('.')) return null;
  return path
    .normalize(path.join(path.dirname(filePath), imported))
    .replace(/\\/g, '/');
}

describe('frontend architecture boundaries', () => {
  it('keeps domain free of React, application, adapters, and API transport', () => {
    const offenders: string[] = [];

    for (const filePath of sourceFiles(path.join(SRC_DIR, 'domain'))) {
      for (const imported of importsFrom(filePath)) {
        const resolved = resolvedRelativeImport(filePath, imported);
        if (
          imported === 'react' ||
          imported.startsWith('react/') ||
          resolved?.includes('/src/application/') ||
          resolved?.includes('/src/adapters/') ||
          resolved?.includes('/src/infrastructure/') ||
          resolved?.includes('/src/components/') ||
          resolved?.includes('/src/contexts/') ||
          resolved?.includes('/src/services/')
        ) {
          offenders.push(`${rel(filePath)} imports ${imported}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('keeps application services free of React adapters and components', () => {
    const offenders: string[] = [];

    for (const filePath of sourceFiles(path.join(SRC_DIR, 'application'))) {
      for (const imported of importsFrom(filePath)) {
        const resolved = resolvedRelativeImport(filePath, imported);
        if (
          imported === 'react' ||
          imported.startsWith('react/') ||
          resolved?.includes('/src/adapters/') ||
          resolved?.includes('/src/components/') ||
          resolved?.includes('/src/contexts/') ||
          resolved?.includes('/src/services/')
        ) {
          offenders.push(`${rel(filePath)} imports ${imported}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
