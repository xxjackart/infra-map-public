'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const map = require(path.join(__dirname, '..', 'docs', 'map.js'));

/**
 * Minimal stand-in for a station button: docs/map.js only reads dataset and
 * the <strong> label, so no DOM implementation is required.
 */
function stationElement(overrides = {}) {
  const data = {
    station: 'n8n',
    line: 'data',
    position: '2',
    detail: 'Workflows and ETL',
    description: 'Workflows ingest and route content.',
    tools: 'n8n|ETL|Routing',
    ...overrides
  };
  return {
    dataset: data,
    querySelector(selector) {
      assert.equal(selector, 'strong', 'createStationModel should read the <strong> label');
      return { textContent: overrides.title ?? 'n8n' };
    }
  };
}

const ORDER_16 = [
  'sources', 'n8n', 'openwebui', 'qdrant', 'records',
  'human', 'opencode', 'mcp', 'decisions', 'outcomes',
  'network', 'caddy', 'infisical', 'recovery', 'observability', 'models'
];

function stationsFor(order, lineFor) {
  return Object.fromEntries(order.map((id, index) => [id, {
    line: lineFor(id, index),
    position: index
  }]));
}

test('UMD module exposes exactly the documented API', () => {
  assert.deepEqual(Object.keys(map).sort(), [
    'LINE_COLORS',
    'LINE_NAMES',
    'adjacentId',
    'createOrder',
    'createStationModel',
    'defaultMeta',
    'externalCount',
    'hasStation',
    'lineCount'
  ]);
  for (const key of Object.keys(map)) {
    if (key === 'LINE_NAMES' || key === 'LINE_COLORS') continue;
    assert.equal(typeof map[key], 'function', `${key} should be a function`);
  }
});

test('LINE_NAMES and LINE_COLORS map every supported line', () => {
  assert.deepEqual(map.LINE_NAMES, {
    data: 'DATA',
    agency: 'AGENCY',
    trust: 'TRUST',
    external: 'EXTERNAL'
  });
  assert.deepEqual(map.LINE_COLORS, {
    data: 'teal',
    agency: 'violet',
    trust: 'acid',
    external: 'orange'
  });
  assert.deepEqual(Object.keys(map.LINE_NAMES).sort(), Object.keys(map.LINE_COLORS).sort());
});

test('createStationModel parses dataset and label into a station record', () => {
  const model = map.createStationModel([stationElement()]);
  assert.deepEqual(model, {
    n8n: {
      line: 'data',
      position: 2,
      title: 'n8n',
      subtitle: 'Workflows and ETL',
      description: 'Workflows ingest and route content.',
      tools: ['n8n', 'ETL', 'Routing']
    }
  });
});

test('createStationModel coerces position to a number and splits tools on pipes', () => {
  const model = map.createStationModel([
    stationElement({ station: 'a', position: '01', tools: 'one|two|three' }),
    stationElement({ station: 'b', position: '0', tools: 'solo' }),
    stationElement({ station: 'c', position: '5', tools: 'A|B', title: 'C title' })
  ]);
  assert.equal(model.a.position, 1);
  assert.equal(model.b.position, 0);
  assert.equal(model.c.position, 5);
  assert.deepEqual(model.a.tools, ['one', 'two', 'three']);
  assert.deepEqual(model.b.tools, ['solo']);
  assert.deepEqual(model.c.tools, ['A', 'B']);
  assert.equal(model.c.title, 'C title');
});

test('createStationModel keeps document order and handles an empty list', () => {
  const model = map.createStationModel([
    stationElement({ station: 'first' }),
    stationElement({ station: 'second' })
  ]);
  assert.deepEqual(Object.keys(model), ['first', 'second']);
  assert.deepEqual(map.createStationModel([]), {});
});

test('createOrder follows DOM order', () => {
  const elements = ORDER_16.map(id => stationElement({ station: id }));
  assert.deepEqual(map.createOrder(elements), ORDER_16);
  assert.deepEqual(map.createOrder([]), []);
});

test('hasStation accepts own keys and rejects inherited Object keys', () => {
  const stations = map.createStationModel([
    stationElement({ station: 'sources' }),
    stationElement({ station: 'toString' })
  ]);
  assert.equal(map.hasStation(stations, 'sources'), true);
  assert.equal(map.hasStation(stations, 'toString'), true, 'own key shadows the prototype');

  const empty = {};
  for (const key of [
    'toString', 'constructor', 'hasOwnProperty', 'valueOf', '__proto__',
    'isPrototypeOf', 'propertyIsEnumerable', 'toLocaleString', 'length'
  ]) {
    assert.equal(map.hasStation(empty, key), false, `${key} must not be treated as a station`);
  }

  const inheritedOnly = Object.create({ ghost: { line: 'data' } });
  assert.equal(map.hasStation(inheritedOnly, 'ghost'), false);
  assert.equal(map.hasStation(empty, ''), false);
});

test('adjacentId walks forward and backward with wraparound', () => {
  assert.equal(map.adjacentId(ORDER_16, 'sources', 1), 'n8n');
  assert.equal(map.adjacentId(ORDER_16, 'sources', -1), 'models', 'first wraps to last');
  assert.equal(map.adjacentId(ORDER_16, 'models', 1), 'sources', 'last wraps to first');
  assert.equal(map.adjacentId(ORDER_16, 'models', -1), 'observability');
  assert.equal(map.adjacentId(ORDER_16, 'n8n', 0), 'n8n');
});

test('adjacentId normalises multi-step and multi-wrap deltas', () => {
  assert.equal(map.adjacentId(ORDER_16, 'records', 2), 'opencode');
  assert.equal(map.adjacentId(ORDER_16, 'human', -2), 'qdrant');
  assert.equal(map.adjacentId(ORDER_16, 'sources', ORDER_16.length), 'sources');
  assert.equal(map.adjacentId(ORDER_16, 'sources', ORDER_16.length + 3), 'qdrant');
  assert.equal(map.adjacentId(ORDER_16, 'n8n', -ORDER_16.length - 1), 'sources');
  assert.equal(map.adjacentId(ORDER_16, 'sources', 16 * 5), 'sources');
});

test('adjacentId returns null for unknown ids and supports a single station', () => {
  assert.equal(map.adjacentId(ORDER_16, 'missing', 1), null);
  assert.equal(map.adjacentId(ORDER_16, 'toString', 1), null);
  assert.equal(map.adjacentId([], 'sources', 1), null);
  assert.equal(map.adjacentId(['only'], 'only', 1), 'only');
  assert.equal(map.adjacentId(['only'], 'only', -1), 'only');
});

test('lineCount counts distinct non-external lines', () => {
  const order = ['a', 'b', 'c', 'd', 'e'];
  const stations = {
    a: { line: 'data' },
    b: { line: 'data' },
    c: { line: 'trust' },
    d: { line: 'external' },
    e: { line: 'agency' }
  };
  assert.equal(map.lineCount(stations, order), 3);
  assert.equal(map.lineCount(stations, order.slice(0, 2)), 1);
  assert.equal(map.lineCount(stations, ['d']), 0);
  assert.equal(map.lineCount(stations, []), 0);
});

test('externalCount counts external stations in order', () => {
  const stations = {
    a: { line: 'data' },
    b: { line: 'external' },
    c: { line: 'external' },
    d: { line: 'trust' }
  };
  assert.equal(map.externalCount(['a', 'b', 'c', 'd'], stations), 2);
  assert.equal(map.externalCount(['a', 'd'], stations), 0);
  assert.equal(map.externalCount([], stations), 0);
});

test('defaultMeta renders the v6.2 default 3-line metadata', () => {
  const stations = stationsFor(ORDER_16, id =>
    ['sources', 'n8n', 'openwebui', 'qdrant', 'records'].includes(id) ? 'data'
      : ['human', 'opencode', 'mcp', 'decisions', 'outcomes'].includes(id) ? 'agency'
        : id === 'models' ? 'external' : 'trust');
  assert.deepEqual(map.defaultMeta(stations, ORDER_16), [
    '16 stations',
    '3 lines',
    '1 external boundary'
  ]);
});

test('defaultMeta pluralises external boundaries and reports zero', () => {
  const stations = {
    a: { line: 'data' },
    b: { line: 'trust' },
    c: { line: 'external' },
    d: { line: 'external' }
  };
  assert.deepEqual(map.defaultMeta(stations, ['a', 'b', 'c', 'd']), [
    '4 stations',
    '2 lines',
    '2 external boundaries'
  ]);
  assert.deepEqual(map.defaultMeta(stations, ['a', 'b']), [
    '2 stations',
    '2 lines',
    '0 external boundaries'
  ]);
});

test('defaultMeta singularises one station and one line', () => {
  assert.deepEqual(map.defaultMeta({ a: { line: 'data' } }, ['a']), [
    '1 station',
    '1 line',
    '0 external boundaries'
  ]);
  assert.deepEqual(map.defaultMeta({ a: { line: 'data' }, b: { line: 'data' } }, ['a', 'b']), [
    '2 stations',
    '1 line',
    '0 external boundaries'
  ]);
});

test('defaultMeta always returns exactly three strings', () => {
  const stations = stationsFor(ORDER_16, () => 'data');
  const meta = map.defaultMeta(stations, ORDER_16);
  assert.equal(meta.length, 3);
  assert.equal(meta.every(value => typeof value === 'string'), true);
  assert.equal(meta.some(value => value.includes('\u2014')), false);
});
