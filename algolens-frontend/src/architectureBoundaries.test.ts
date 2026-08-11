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

function resolvedSourceImport(filePath: string, imported: string): string | null {
  if (imported.startsWith('@/')) {
    return path.normalize(path.join(SRC_DIR, imported.slice(2))).replace(/\\/g, '/');
  }

  if (imported.startsWith('.')) {
    return path
      .normalize(path.join(path.dirname(filePath), imported))
      .replace(/\\/g, '/');
  }

  return null;
}

function importsReact(imported: string): boolean {
  return imported === 'react' || imported.startsWith('react/');
}

function importsSourceFolder(resolved: string | null, folder: string): boolean {
  return resolved?.includes(`/src/${folder}/`) ?? false;
}

describe('frontend architecture boundaries', () => {
  it('keeps models free of React and outward application code', () => {
    const offenders: string[] = [];

    for (const filePath of sourceFiles(path.join(SRC_DIR, 'models'))) {
      for (const imported of importsFrom(filePath)) {
        const resolved = resolvedSourceImport(filePath, imported);
        if (
          importsReact(imported) ||
          importsSourceFolder(resolved, 'application') ||
          importsSourceFolder(resolved, 'adapters') ||
          importsSourceFolder(resolved, 'infrastructure') ||
          importsSourceFolder(resolved, 'components')
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
        const resolved = resolvedSourceImport(filePath, imported);
        if (
          importsReact(imported) ||
          importsSourceFolder(resolved, 'adapters') ||
          importsSourceFolder(resolved, 'components') ||
          importsSourceFolder(resolved, 'contexts') ||
          importsSourceFolder(resolved, 'services')
        ) {
          offenders.push(`${rel(filePath)} imports ${imported}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
