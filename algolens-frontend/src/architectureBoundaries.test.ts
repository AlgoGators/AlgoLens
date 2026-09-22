import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const SRC_DIR = path.join(process.cwd(), 'src');

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
  return importsFromSource(source, filePath);
}

function importsFromSource(source: string, fileName = 'fixture.ts'): string[] {
  const parsed = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true);
  const imports: string[] = [];

  const visit = (node: ts.Node) => {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)
    ) {
      imports.push(node.moduleSpecifier.text);
    } else if (
      ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0])
    ) {
      imports.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  };
  visit(parsed);
  return imports;
}

function rel(filePath: string): string {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

function resolvedImport(filePath: string, imported: string): string | null {
  const resolved = imported === '@' || imported.startsWith('@/')
    ? path.join(SRC_DIR, imported === '@' ? '' : imported.slice(2))
    : imported.startsWith('.')
      ? path.join(path.dirname(filePath), imported)
      : null;
  return resolved ? path.normalize(resolved).replace(/\\/g, '/') : null;
}

describe('frontend architecture boundaries', () => {
  it('extracts aliases, re-exports, and dynamic imports from real TypeScript syntax', () => {
    const source = `
      import type { Api } from '@/infrastructure/api/portfolioApi';
      export { thing } from '../application/thing';
      const lazy = import("@/components/LazyPanel");
    `;

    expect(importsFromSource(source)).toEqual([
      '@/infrastructure/api/portfolioApi',
      '../application/thing',
      '@/components/LazyPanel',
    ]);
  });

  it('resolves the configured @ alias into src for boundary rules', () => {
    const file = path.join(SRC_DIR, 'domain', 'portfolio', 'example.ts');
    expect(resolvedImport(file, '@/infrastructure/api/portfolioApi'))
      .toContain('/src/infrastructure/api/portfolioApi');
  });

  it('keeps domain free of React, application, adapters, and API transport', () => {
    const offenders: string[] = [];

    for (const filePath of sourceFiles(path.join(SRC_DIR, 'domain'))) {
      for (const imported of importsFrom(filePath)) {
        const resolved = resolvedImport(filePath, imported);
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
        const resolved = resolvedImport(filePath, imported);
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
