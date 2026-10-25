(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.InfraMap = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const LINE_NAMES = { data: 'DATA', agency: 'AGENCY', trust: 'TRUST', external: 'EXTERNAL' };
  const LINE_COLORS = { data: 'teal', agency: 'violet', trust: 'acid', external: 'orange' };

  function createStationModel(elements) {
    return Object.fromEntries(elements.map(element => {
      const data = element.dataset;
      return [data.station, {
        line: data.line,
        position: Number(data.position),
        title: element.querySelector('strong').textContent,
        subtitle: data.detail,
        description: data.description,
        tools: data.tools.split('|')
      }];
    }));
  }

  function createOrder(elements) {
    return elements.map(element => element.dataset.station);
  }

  function hasStation(stations, id) {
    return Object.hasOwn(stations, id);
  }

  function adjacentId(order, id, delta) {
    const index = order.indexOf(id);
    if (index < 0) return null;
    return order[(index + delta + order.length) % order.length];
  }

  function lineCount(stations, order) {
    return new Set(order.map(id => stations[id].line).filter(line => line !== 'external')).size;
  }

  function externalCount(order, stations) {
    return order.filter(id => stations[id].line === 'external').length;
  }

  function defaultMeta(stations, order) {
    const external = externalCount(order, stations);
    const stationTotal = order.length;
    const lineTotal = lineCount(stations, order);
    return [
      `${stationTotal} ${stationTotal === 1 ? 'station' : 'stations'}`,
      `${lineTotal} ${lineTotal === 1 ? 'line' : 'lines'}`,
      `${external} external ${external === 1 ? 'boundary' : 'boundaries'}`
    ];
  }

  return { LINE_NAMES, LINE_COLORS, createStationModel, createOrder, hasStation, adjacentId, lineCount, externalCount, defaultMeta };
});

if (typeof document !== 'undefined') {
  const stationElements = [...document.querySelectorAll('.station')];
  const STATIONS = InfraMap.createStationModel(stationElements);
  const ORDER = InfraMap.createOrder(stationElements);
  const { LINE_NAMES, LINE_COLORS } = InfraMap;
  const atlas = document.getElementById('atlas');
  const viewport = document.getElementById('atlas-viewport');
  const resetButton = document.getElementById('atlas-reset');
  const status = document.getElementById('line-status');
  const detailIcon = document.getElementById('detail-icon');
  const detailKicker = document.getElementById('detail-kicker');
  const detailTitle = document.getElementById('detail-title');
  const detailDescription = document.getElementById('detail-description');
  const detailTools = document.getElementById('detail-tools');
  const previousButton = document.getElementById('detail-prev');
  const nextButton = document.getElementById('detail-next');
  const SCROLL_BEHAVIOR = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  const DEFAULT_DETAIL = {
    icon: detailIcon.cloneNode(true),
    kicker: detailKicker.textContent,
    title: detailTitle.textContent,
    description: detailDescription.textContent
  };
  let selectedId = null;

  function makeChip(text) {
    const chip = document.createElement('span');
    chip.textContent = text;
    return chip;
  }

  function fillDefaultMeta() {
    detailTools.replaceChildren(...InfraMap.defaultMeta(STATIONS, ORDER).map(makeChip));
  }

  function updatePanHint() {
    document.querySelector('.map-pan-hint').style.display = viewport.scrollWidth > viewport.clientWidth ? 'block' : 'none';
  }

  if ('ResizeObserver' in window) new ResizeObserver(updatePanHint).observe(viewport);
  else window.addEventListener('resize', updatePanHint);
  updatePanHint();

  function ensureVisible(element) {
    const view = viewport.getBoundingClientRect();
    const box = element.getBoundingClientRect();
    if (box.left < view.left + 18) viewport.scrollLeft -= view.left + 18 - box.left;
    if (box.right > view.right - 18) viewport.scrollLeft += box.right - (view.right - 18);
  }

  function selectStation(id, options = {}) {
    if (!InfraMap.hasStation(STATIONS, id)) return;
    const station = STATIONS[id];
    selectedId = id;
    atlas.classList.add('has-focus');
    stationElements.forEach(element => {
      const active = element.dataset.station === id;
      const sameLine = element.dataset.line === station.line;
      element.classList.toggle('is-selected', active);
      element.classList.toggle('is-active-line', sameLine);
      element.setAttribute('aria-pressed', String(active));
      if (active && options.ensureMapVisible !== false) ensureVisible(element);
    });
    document.querySelectorAll('.metro-line').forEach(path => path.classList.toggle('is-active', path.classList.contains(`line-${station.line}`)));
    document.querySelectorAll('.metro-external').forEach(path => path.classList.toggle('is-active', station.line === 'external'));
    const total = ORDER.filter(stationId => STATIONS[stationId].line === station.line).length;
    status.textContent = `${LINE_NAMES[station.line]} · ${station.title} · ${station.position}/${total}`;
    status.style.color = `var(--${LINE_COLORS[station.line]})`;
    const sourceToken = document.querySelector(`[data-station="${id}"] .station-token`).cloneNode(true);
    detailIcon.replaceChildren(sourceToken);
    detailKicker.textContent = `${LINE_NAMES[station.line]} / ${station.subtitle}`;
    detailTitle.textContent = station.title;
    detailDescription.textContent = station.description;
    detailTools.replaceChildren(...station.tools.map(makeChip));
    const previousId = InfraMap.adjacentId(ORDER, id, -1);
    const nextId = InfraMap.adjacentId(ORDER, id, 1);
    previousButton.disabled = false;
    nextButton.disabled = false;
    previousButton.textContent = `← ${STATIONS[previousId].title}`;
    nextButton.textContent = `${STATIONS[nextId].title} →`;
    resetButton.disabled = false;
    history.replaceState(null, '', `#map-${id}`);
    if (options.scrollDetail) document.getElementById('station-detail').scrollIntoView({ behavior: SCROLL_BEHAVIOR, block: 'nearest' });
  }

  function resetMap() {
    selectedId = null;
    viewport.scrollLeft = 0;
    atlas.classList.remove('has-focus');
    stationElements.forEach(element => {
      element.classList.remove('is-selected', 'is-active-line');
      element.setAttribute('aria-pressed', 'false');
    });
    document.querySelectorAll('.metro-line, .metro-external').forEach(path => path.classList.remove('is-active'));
    status.textContent = 'All lines / select a station';
    status.style.color = 'var(--teal)';
    detailIcon.replaceChildren(DEFAULT_DETAIL.icon.cloneNode(true));
    detailKicker.textContent = DEFAULT_DETAIL.kicker;
    detailTitle.textContent = DEFAULT_DETAIL.title;
    detailDescription.textContent = DEFAULT_DETAIL.description;
    fillDefaultMeta();
    previousButton.disabled = true;
    nextButton.disabled = true;
    previousButton.textContent = '← Previous';
    nextButton.textContent = 'Next station →';
    resetButton.disabled = true;
    history.replaceState(null, '', '#system');
  }

  stationElements.forEach(element => element.addEventListener('click', () => selectStation(element.dataset.station, { scrollDetail: true })));
  previousButton.addEventListener('click', () => selectStation(InfraMap.adjacentId(ORDER, selectedId, -1), { ensureMapVisible: true }));
  nextButton.addEventListener('click', () => selectStation(InfraMap.adjacentId(ORDER, selectedId, 1), { ensureMapVisible: true }));
  resetButton.addEventListener('click', resetMap);
  window.addEventListener('hashchange', () => {
    const id = location.hash.startsWith('#map-') ? location.hash.slice(5) : null;
    if (id && InfraMap.hasStation(STATIONS, id)) selectStation(id, { ensureMapVisible: true });
  });
  const initialStation = location.hash.startsWith('#map-') ? location.hash.slice(5) : null;
  fillDefaultMeta();
  if (initialStation && InfraMap.hasStation(STATIONS, initialStation)) selectStation(initialStation, { ensureMapVisible: true });
}
