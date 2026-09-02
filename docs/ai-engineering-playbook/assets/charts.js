(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var success = style.getPropertyValue('--success').trim();
  var warning = style.getPropertyValue('--warning').trim();

  // --- Chart: 三模型横向对比 ---
  var chart1 = echarts.init(document.getElementById('chart-model-compare'), null, { renderer: 'svg' });
  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: {
      data: ['格式合规', '真实性', '综合质量'],
      bottom: 0,
      textStyle: { color: muted, fontSize: 12 }
    },
    grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ['Qwen 7B', 'GLM 5.3 Flash', 'Claude Opus 5'],
      axisLabel: { color: muted, fontSize: 12 },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      axisLabel: { color: muted, fontSize: 11 },
      splitLine: { lineStyle: { color: rule } }
    },
    series: [
      {
        name: '格式合规',
        type: 'bar',
        data: [1.00, 1.00, 1.00],
        itemStyle: { color: accent },
        barWidth: '18%'
      },
      {
        name: '真实性',
        type: 'bar',
        data: [0.00, 0.75, 0.95],
        itemStyle: { color: accent2 },
        barWidth: '18%'
      },
      {
        name: '综合质量',
        type: 'bar',
        data: [0.42, 0.92, 0.86],
        itemStyle: { color: success },
        barWidth: '18%'
      }
    ]
  });
  window.addEventListener('resize', function() { chart1.resize(); });

  // --- Chart: Prompt 迭代质量变化 ---
  var chart2 = echarts.init(document.getElementById('chart-prompt-iter'), null, { renderer: 'svg' });
  chart2.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: {
      data: ['真实性', '综合质量'],
      bottom: 0,
      textStyle: { color: muted, fontSize: 12 }
    },
    grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ['v1 (初始)', 'v2 (加来源字段)', 'v3 (真实性红线)'],
      axisLabel: { color: muted, fontSize: 12 },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'value',
      min: 0.6,
      max: 1,
      axisLabel: { color: muted, fontSize: 11 },
      splitLine: { lineStyle: { color: rule } }
    },
    series: [
      {
        name: '真实性',
        type: 'line',
        data: [0.73, 0.81, 0.75],
        smooth: true,
        lineStyle: { color: accent2, width: 2 },
        itemStyle: { color: accent2 },
        symbol: 'circle',
        symbolSize: 8
      },
      {
        name: '综合质量',
        type: 'line',
        data: [0.96, 0.88, 0.92],
        smooth: true,
        lineStyle: { color: accent, width: 2 },
        itemStyle: { color: accent },
        symbol: 'circle',
        symbolSize: 8
      }
    ]
  });
  window.addEventListener('resize', function() { chart2.resize(); });
})();
