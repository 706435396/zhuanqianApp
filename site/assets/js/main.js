/* ==========================================================================
   副业工坊 · 交互脚本（原生 JS，无依赖）
   - 返回顶部
   - 订阅表单演示
   - 文章复制链接
   - 站内搜索（读取 search-index.json）
   ========================================================================== */
(function () {
  'use strict';

  /* ---------- 返回顶部 ---------- */
  var backtop = document.getElementById('backtop');
  if (backtop) {
    window.addEventListener('scroll', function () {
      if (window.scrollY > 400) backtop.classList.add('show');
      else backtop.classList.remove('show');
    });
    backtop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ---------- 订阅表单（演示版：替换为你的邮件服务 API） ---------- */
  var subForm = document.getElementById('subscribe-form');
  if (subForm) {
    subForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var input = subForm.querySelector('input');
      var btn = subForm.querySelector('button');
      var email = input.value.trim();
      if (!email) return;
      var old = btn.textContent;
      btn.textContent = '✓ 订阅成功';
      btn.style.background = '#16a34a';
      input.value = '';
      // TODO: 接入真实的邮件订阅服务（如 MailerLite / ConvertKit / CF Worker）
      // fetch('/api/subscribe', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:email})});
      setTimeout(function () { btn.textContent = old; btn.style.background = ''; }, 3000);
    });
  }

  /* ---------- 站内搜索 ---------- */
  var searchInput = document.getElementById('search-input');
  if (searchInput) {
    var resultsEl = document.getElementById('search-results');
    var countEl = document.getElementById('search-count');
    var index = [];

    fetch('/search-index.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; render(''); })
      .catch(function () { countEl.textContent = '索引加载失败'; });

    function esc(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    }

    function card(item) {
      return '<a class="post-card compact" href="' + esc(item.url) + '" style="--cat-color:' + esc(item.color) + '">' +
        '<div class="post-cover" style="--cover-color:' + esc(item.color) + '"><span>' + esc(item.emoji) + '</span></div>' +
        '<div class="post-body">' +
        '<div class="post-meta"><span class="cat-pill">' + esc(item.category) + '</span></div>' +
        '<h3>' + esc(item.title) + '</h3>' +
        '<p>' + esc(item.excerpt) + '</p>' +
        '</div></a>';
    }

    function render(q) {
      q = q.trim().toLowerCase();
      var list;
      if (!q) {
        list = index.slice(0, 6);
        countEl.textContent = index.length + ' 篇文章';
      } else {
        var words = q.split(/\s+/);
        list = index.filter(function (item) {
          return words.every(function (w) { return item.text.indexOf(w) !== -1; });
        });
        countEl.textContent = '找到 ' + list.length + ' 篇';
      }
      resultsEl.innerHTML = list.length
        ? list.map(card).join('')
        : '<p class="empty">没有找到相关内容，换个关键词试试 🔍</p>';
    }

    var timer;
    searchInput.addEventListener('input', function () {
      clearTimeout(timer);
      var val = searchInput.value;
      timer = setTimeout(function () { render(val); }, 150);
    });

    document.querySelectorAll('.quick-tag').forEach(function (btn) {
      btn.addEventListener('click', function () {
        searchInput.value = btn.dataset.q;
        render(btn.dataset.q);
        searchInput.focus();
      });
    });
  }
})();

/* ==========================================================================
   排行榜筛选：提现速度 / 单价 / 适合人群 + 多维排序 + 关键词搜索
   ========================================================================== */
(function () {
  'use strict';

  // 通用筛选：每个 [data-filter-scope] 容器独立筛自己的 .filter-item
  // 排行榜与分类页共用同一套逻辑，维度取自每项的 data-* 属性
  function initScope(scope) {
    var list = scope.querySelector('.filter-list');
    if (!list) return;

    var items = Array.prototype.slice.call(list.querySelectorAll('.filter-item'));
    var groups = scope.querySelectorAll('.filter-chips[data-filter]');
    var countEl = scope.querySelector('[data-filter-count]');
    var emptyEl = scope.querySelector('[data-filter-empty]');
    var searchEl = scope.querySelector('[data-filter-search]');
    var resetEl = scope.querySelector('[data-filter-reset]');
    var state = { wd: 'all', price: 'all', aud: 'all', sort: 'score', q: '' };
    // 该 scope 实际存在的筛选维度（分类页可能没有 aud）
    var dims = {};
    groups.forEach(function (g) { dims[g.getAttribute('data-filter')] = true; });

    var base = items.map(function (el, i) {
      return {
        el: el,
        pos: i,
        name: (el.getAttribute('data-name') || '').toLowerCase(),
        cat: (el.getAttribute('data-cat') || '').toLowerCase(),
        wd: parseFloat(el.getAttribute('data-wd') || '1'),
        price: parseFloat(el.getAttribute('data-price') || '2'),
        rating: parseFloat(el.getAttribute('data-rating') || '0'),
        score: parseFloat(el.getAttribute('data-score') || '0'),
        aud: (el.getAttribute('data-aud') || '').split(',').filter(Boolean)
      };
    });

    function apply() {
      var q = state.q.trim().toLowerCase();
      var matched = base.filter(function (d) {
        if (state.wd !== 'all' && d.wd !== parseFloat(state.wd)) return false;
        if (state.price !== 'all' && d.price !== parseFloat(state.price)) return false;
        if (state.aud !== 'all' && d.aud.indexOf(state.aud) === -1) return false;
        if (q && d.name.indexOf(q) === -1 && d.cat.indexOf(q) === -1) return false;
        return true;
      });

      var key = state.sort;
      matched.sort(function (a, b) {
        if (key === 'wd') return a.wd - b.wd || b.score - a.score;
        if (key === 'price') return b.price - a.price || b.score - a.score;
        if (key === 'rating') return b.rating - a.rating || b.score - a.score;
        return b.score - a.score || a.pos - b.pos;
      });

      var frag = document.createDocumentFragment();
      matched.forEach(function (d, i) {
        var badge = d.el.querySelector('.rank-no');
        if (badge) badge.textContent = i + 1;
        frag.appendChild(d.el);
      });
      list.appendChild(frag);

      list.hidden = matched.length === 0;
      if (emptyEl) emptyEl.hidden = matched.length !== 0;
      if (countEl) countEl.textContent = matched.length;
    }

    groups.forEach(function (group) {
      group.addEventListener('click', function (e) {
        var btn = e.target.closest('.fchip');
        if (!btn || !group.contains(btn)) return;
        group.querySelectorAll('.fchip').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state[group.getAttribute('data-filter')] = btn.getAttribute('data-val');
        apply();
      });
    });

    if (searchEl) {
      var timer;
      searchEl.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { state.q = searchEl.value; apply(); }, 120);
      });
    }

    if (resetEl) {
      resetEl.addEventListener('click', function (e) {
        e.preventDefault();
        state = { wd: 'all', price: 'all', aud: 'all', sort: 'score', q: '' };
        groups.forEach(function (group) {
          group.querySelectorAll('.fchip').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-val') === 'all' ||
              (group.getAttribute('data-filter') === 'sort' && b.getAttribute('data-val') === 'score'));
          });
        });
        if (searchEl) searchEl.value = '';
        apply();
      });
    }
  }

  document.querySelectorAll('[data-filter-scope]').forEach(initScope);
})();

/* 文章分享：复制当前链接 */
function shareNow(event) {
  event.preventDefault();
  var url = window.location.href;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(function () {
      alert('链接已复制，快分享给朋友吧 🔗');
    });
  } else {
    var ta = document.createElement('textarea');
    ta.value = url;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    alert('链接已复制，快分享给朋友吧 🔗');
  }
  return false;
}
