(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var danger = style.getPropertyValue('--danger').trim();
  var warning = style.getPropertyValue('--warning').trim();

  // --- Chart 1: 三轮评测指标对比 ---
  var chart1 = echarts.init(document.getElementById('chart-rounds'), null, { renderer: 'svg' });
  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: {
      data: ['泰国相关度MAE', '商机强度MAE', '时效性分桶准确率', '板块准确率'],
      bottom: 0,
      textStyle: { color: muted, fontSize: 11 }
    },
    grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ['第一轮', '第二轮', '第三轮'],
      axisLabel: { color: muted, fontSize: 12 },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: [
      { type: 'value', name: 'MAE', min: 0, max: 1.5, axisLabel: { color: muted, fontSize: 11 }, splitLine: { lineStyle: { color: rule } }, nameTextStyle: { color: muted } },
      { type: 'value', name: '准确率', min: 0, max: 1.2, axisLabel: { color: muted, fontSize: 11 }, splitLine: { show: false }, nameTextStyle: { color: muted } }
    ],
    series: [
      { name: '泰国相关度MAE', type: 'bar', data: [0.28, 0.33, 0.30], itemStyle: { color: accent }, barWidth: '15%' },
      { name: '商机强度MAE', type: 'bar', data: [1.07, 1.35, 0.97], itemStyle: { color: danger }, barWidth: '15%' },
      { name: '时效性分桶准确率', type: 'line', yAxisIndex: 1, data: [0.55, 0.68, 1.00], itemStyle: { color: accent2 }, lineStyle: { width: 3 }, symbol: 'circle', symbolSize: 10 },
      { name: '板块准确率', type: 'line', yAxisIndex: 1, data: [1.00, 1.00, 0.97], itemStyle: { color: warning }, lineStyle: { width: 3 }, symbol: 'circle', symbolSize: 10 }
    ]
  });
  window.addEventListener('resize', function() { chart1.resize(); });

  // --- Chart 2: 金标准分数分布散点图 ---
  var chart2 = echarts.init(document.getElementById('chart-scatter'), null, { renderer: 'svg' });
  var scatterData = [
    [10, 3, 3, 'score-001'], [10, 4, 5, 'score-002'], [10, 3, 3, 'score-003'],
    [10, 4, 3, 'score-004'], [8, 3, 5, 'score-005'], [10, 3, 7, 'score-006'],
    [9, 3, 5, 'score-007'], [10, 8, 6, 'score-008'], [10, 10, 10, 'score-009'],
    [10, 10, 10, 'score-010'], [10, 9, 8, 'score-011'], [10, 10, 7, 'score-012'],
    [10, 9, 9, 'score-013'], [10, 9, 3, 'score-014'], [10, 8, 8, 'score-015'],
    [10, 9, 10, 'score-016'], [9, 5, 8, 'score-017'], [10, 3, 3, 'score-018'],
    [9, 8, 8, 'score-019'], [9, 7, 10, 'score-020'], [10, 5, 1, 'score-021'],
    [10, 8, 5, 'score-022'], [10, 8, 6, 'score-023'], [10, 5, 7, 'score-024'],
    [10, 4, 10, 'score-025'], [10, 5, 3, 'score-026'], [10, 5, 6, 'score-027'],
    [10, 4, 3, 'score-028'], [0, 1, 3, 'score-029'], [0, 1, 6, 'score-030'],
    [3, 1, 10, 'score-031'], [4, 2, 9, 'score-032'], [1, 2, 8, 'score-033'],
    [7, 2, 1, 'score-034'], [0, 1, 7, 'score-035'], [10, 3, 6, 'score-036'],
    [10, 4, 3, 'score-037'], [9, 3, 3, 'score-038'], [10, 4, 5, 'score-039'],
    [10, 4, 10, 'score-040']
  ];
  chart2.setOption({
    animation: false,
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      formatter: function(p) {
        return p.data[3] + '<br/>相关度: ' + p.data[0] + '<br/>商机: ' + p.data[1] + '<br/>时效: ' + p.data[2];
      }
    },
    legend: { data: ['金标准用例'], bottom: 0, textStyle: { color: muted, fontSize: 11 } },
    grid: { left: '3%', right: '4%', bottom: '12%', top: '10%', containLabel: true },
    xAxis: { type: 'value', name: '泰国相关度', min: 0, max: 10, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } }, nameTextStyle: { color: muted } },
    yAxis: { type: 'value', name: '商机强度', min: 0, max: 11, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } }, nameTextStyle: { color: muted } },
    visualMap: {
      min: 1, max: 10, dimension: 2, orient: 'horizontal', right: '5%', top: '5%',
      inRange: { color: [bg2, accent2, accent] },
      text: ['时效高', '时效低'], textStyle: { color: muted }
    },
    series: [{
      name: '金标准用例', type: 'scatter', data: scatterData,
      symbolSize: function(d) { return 12 + d[2] * 0.8; },
      itemStyle: { opacity: 0.8 }
    }]
  });
  window.addEventListener('resize', function() { chart2.resize(); });

  // --- Mermaid init ---
  if (typeof mermaid !== 'undefined') {
    mermaid.initialize({ startOnLoad: true, theme: 'dark', securityLevel: 'loose' });
  }
})();
