import { describe, it, expect } from 'vitest';
import de from './de.json';
import en from './en.json';

// ── helpers ──────────────────────────────────────────────────────────

/** Recursively flatten a nested object into dot-separated key paths. */
function flattenKeys(obj: Record<string, any>, prefix = ''): string[] {
  return Object.keys(obj).reduce<string[]>((acc, key) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof obj[key] === 'object' && obj[key] !== null && !Array.isArray(obj[key])) {
      return acc.concat(flattenKeys(obj[key], path));
    }
    return acc.concat(path);
  }, []);
}

/** Get the leaf-key names that live under a specific top-level section. */
function getNestedKeys(obj: Record<string, any>, section: string): string[] {
  if (!obj[section] || typeof obj[section] !== 'object') return [];
  return Object.keys(obj[section]);
}

// ── tour keys ────────────────────────────────────────────────────────

describe('tour keys', () => {
  it('de.json has tour section', () => {
    expect(de).toHaveProperty('tour');
  });

  it('en.json has tour section', () => {
    expect(en).toHaveProperty('tour');
  });

  it('both have identical tour keys', () => {
    const deKeys = getNestedKeys(de, 'tour').sort();
    const enKeys = getNestedKeys(en, 'tour').sort();
    expect(deKeys).toEqual(enKeys);
  });

  it('has required nav keys: skip, next, prev, done, helpButton', () => {
    const required = ['skip', 'next', 'prev', 'done', 'helpButton'];
    for (const key of required) {
      expect(en.tour).toHaveProperty(key);
      expect(de.tour).toHaveProperty(key);
    }
  });

  it('has dashboard tour step keys', () => {
    const dashKeys = [
      'dashPnlTitle', 'dashPnlDesc',
      'dashChartsTitle', 'dashChartsDesc',
      'dashTradesTitle', 'dashTradesDesc',
    ];
    for (const key of dashKeys) {
      expect(en.tour).toHaveProperty(key);
      expect(de.tour).toHaveProperty(key);
    }
  });

  it('has bots tour step keys', () => {
    const botKeys = [
      'botsNewBotTitle', 'botsNewBotDesc',
      'botsBotCardTitle', 'botsBotCardDesc',
      'botsStatsTitle', 'botsStatsDesc',
      'botsActionsTitle', 'botsActionsDesc',
    ];
    for (const key of botKeys) {
      expect(en.tour).toHaveProperty(key);
      expect(de.tour).toHaveProperty(key);
    }
  });

  it('no tour value is empty string', () => {
    const tourValues = Object.values(en.tour as Record<string, string>);
    for (const v of tourValues) {
      expect(v).not.toBe('');
    }
    const deTourValues = Object.values(de.tour as Record<string, string>);
    for (const v of deTourValues) {
      expect(v).not.toBe('');
    }
  });
});

// ── guide quick-start keys ───────────────────────────────────────────

describe('guide quick-start keys', () => {
  const quickStartKeys = ['qsTitle', 'qsSubtitle', 'qsStep1', 'qsStep2', 'qsStep3', 'qsStep4'];

  it('de and en both have quick-start keys', () => {
    for (const key of quickStartKeys) {
      expect(en.guide).toHaveProperty(key);
      expect(de.guide).toHaveProperty(key);
    }
  });
});

// ── guide strategy overview keys ─────────────────────────────────────

describe('guide strategy overview keys', () => {
  const stratKeys = [
    'stratTitle', 'stratSubtitle',
    'stratColName', 'stratColType', 'stratColDesc', 'stratColTf',
    'stratSentiment', 'stratSentimentTf',
    'stratLiquidation', 'stratLiquidationTf',
    'stratEdge', 'stratEdgeTf',
    'stratTypeSentiment', 'stratTypeLiq', 'stratTypeKline',
  ];

  it('de and en both have strategy overview keys', () => {
    for (const key of stratKeys) {
      expect(en.guide).toHaveProperty(key);
      expect(de.guide).toHaveProperty(key);
    }
  });
});

// ── guide section parity ─────────────────────────────────────────────

describe('guide section parity', () => {
  it('both have same number of guide keys', () => {
    const deKeys = getNestedKeys(de, 'guide');
    const enKeys = getNestedKeys(en, 'guide');
    expect(deKeys.length).toBe(enKeys.length);
  });

  it('no guide key missing in either language', () => {
    const deKeys = new Set(getNestedKeys(de, 'guide'));
    const enKeys = new Set(getNestedKeys(en, 'guide'));

    const missingInDe = [...enKeys].filter((k) => !deKeys.has(k));
    const missingInEn = [...deKeys].filter((k) => !enKeys.has(k));

    expect(missingInDe).toEqual([]);
    expect(missingInEn).toEqual([]);
  });
});

// ── trades.exitReasons label uniqueness ──────────────────────────────
// Guards against bug #194: MANUAL_CLOSE and EXTERNAL_CLOSE both mapped
// to the same German label "Manuell geschlossen", making it impossible
// to tell them apart in the UI.

describe('trades.exitReasons label uniqueness', () => {
  const locales = { de, en } as const;
  for (const lang of ['de', 'en'] as const) {
    it(`${lang}: every exit reason has a unique label`, () => {
      const reasons = (locales[lang] as any).trades.exitReasons as Record<string, string>;
      const values = Object.values(reasons);
      const unique = new Set(values);

      if (values.length !== unique.size) {
        // Surface the duplicates for fast debugging.
        const counts = new Map<string, string[]>();
        for (const [code, label] of Object.entries(reasons)) {
          const list = counts.get(label) ?? [];
          list.push(code);
          counts.set(label, list);
        }
        const duplicates = [...counts.entries()].filter(([, codes]) => codes.length > 1);
        throw new Error(
          `Duplicate exit reason labels in ${lang}: ` +
            duplicates.map(([label, codes]) => `"${label}" used by ${codes.join(', ')}`).join('; ')
        );
      }

      expect(values.length).toBe(unique.size);
    });
  }
});

// ── overall parity ───────────────────────────────────────────────────

describe('overall parity', () => {
  it('both have same top-level sections', () => {
    const deSections = Object.keys(de).sort();
    const enSections = Object.keys(en).sort();
    expect(deSections).toEqual(enSections);
  });

  it('total key count is identical', () => {
    const deTotal = flattenKeys(de).length;
    const enTotal = flattenKeys(en).length;
    expect(deTotal).toBe(enTotal);
  });

  it('no key missing in either language (full dot-path parity)', () => {
    const deKeys = new Set(flattenKeys(de));
    const enKeys = new Set(flattenKeys(en));

    const missingInDe = [...enKeys].filter((k) => !deKeys.has(k)).sort();
    const missingInEn = [...deKeys].filter((k) => !enKeys.has(k)).sort();

    if (missingInDe.length > 0 || missingInEn.length > 0) {
      // Surface the exact gaps for fast debugging when CI fails.
      const msg = [
        missingInDe.length > 0
          ? `Missing in de.json (${missingInDe.length}):\n  ${missingInDe.join('\n  ')}`
          : '',
        missingInEn.length > 0
          ? `Missing in en.json (${missingInEn.length}):\n  ${missingInEn.join('\n  ')}`
          : '',
      ]
        .filter(Boolean)
        .join('\n');
      throw new Error(`i18n parity broken:\n${msg}`);
    }

    expect(missingInDe).toEqual([]);
    expect(missingInEn).toEqual([]);
  });

  it('no structural mismatches (leaf vs object) between de and en', () => {
    function walk(
      a: Record<string, any>,
      b: Record<string, any>,
      prefix = ''
    ): Array<{ path: string; de: string; en: string }> {
      const mismatches: Array<{ path: string; de: string; en: string }> = [];
      const shared = Object.keys(a).filter((k) => k in b);
      for (const key of shared) {
        const path = prefix ? `${prefix}.${key}` : key;
        const va = a[key];
        const vb = b[key];
        const ta =
          va !== null && typeof va === 'object' && !Array.isArray(va) ? 'object' : 'leaf';
        const tb =
          vb !== null && typeof vb === 'object' && !Array.isArray(vb) ? 'object' : 'leaf';
        if (ta !== tb) {
          mismatches.push({ path, de: ta, en: tb });
        } else if (ta === 'object') {
          mismatches.push(...walk(va, vb, path));
        }
      }
      return mismatches;
    }

    const mismatches = walk(de as Record<string, any>, en as Record<string, any>);
    if (mismatches.length > 0) {
      const details = mismatches
        .map((m) => `  ${m.path}: de=${m.de} vs en=${m.en}`)
        .join('\n');
      throw new Error(`Structural mismatches between de.json and en.json:\n${details}`);
    }
    expect(mismatches).toEqual([]);
  });
});
