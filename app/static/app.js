function postAjax(url, formData) {
  return fetch(url, {
    method: 'POST',
    headers: { 'X-Requested-With': 'fetch' },
    body: formData,
  });
}

// PUBLIC_MODE（お試し公開用インスタンス）では、スキルシート・働き方の希望条件・履歴を
// サーバーに保存せず、このブラウザのlocalStorageにのみ保存する。
var JobFitStorage = (function () {
  var SKILL_SHEET_KEY = 'jobfit_skill_sheet';
  var WORK_STYLE_KEY = 'jobfit_work_style';
  var HISTORY_KEY = 'jobfit_history';

  function readJSON(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function writeJSON(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {}
  }

  return {
    getSkillSheet: function () {
      try {
        return localStorage.getItem(SKILL_SHEET_KEY) || '';
      } catch (e) {
        return '';
      }
    },
    setSkillSheet: function (text) {
      try {
        localStorage.setItem(SKILL_SHEET_KEY, text || '');
      } catch (e) {}
    },
    hasSkillSheet: function () {
      return !!this.getSkillSheet();
    },
    getWorkStyle: function () {
      return readJSON(WORK_STYLE_KEY, {});
    },
    setWorkStyle: function (data) {
      writeJSON(WORK_STYLE_KEY, data || {});
    },
    getHistory: function () {
      return readJSON(HISTORY_KEY, []);
    },
    pushHistoryEntry: function (entry) {
      var list = this.getHistory();
      list.unshift(entry);
      writeJSON(HISTORY_KEY, list);
    },
    updateHistoryOutcome: function (id, outcome, reason) {
      var list = this.getHistory();
      for (var i = 0; i < list.length; i++) {
        if (list[i].id === id) {
          list[i].outcome = outcome;
          list[i].outcome_reason = reason;
          break;
        }
      }
      writeJSON(HISTORY_KEY, list);
    },
  };
})();

// 履歴画面の「選考結果」フォームの配線。PUBLIC_MODEではlocalStorageのみを更新し、
// それ以外ではサーバーに保存する。サーバー保存済みの内容（初回表示）にも、
// /history/renderで差し替えた内容にも使う。
function wireHistoryContent(container) {
  container.querySelectorAll('.outcome-control').forEach(function (control) {
    var entryId = control.dataset.entryId;
    var select = control.querySelector('.outcome-select');
    var reasonInput = control.querySelector('.reason-input');
    var errorEl = control.querySelector('.outcome-error');

    select.dataset.savedValue = select.value;
    reasonInput.dataset.savedValue = reasonInput.value;

    function applyBadge(outcome) {
      var badge = control.closest('details').querySelector('.outcome-badge');
      badge.textContent = outcome;
      badge.hidden = !outcome;
      var badgeClass = outcome ? (OUTCOME_BADGE_CLASSES[outcome] || OUTCOME_BADGE_DEFAULT_CLASS) : '';
      badge.className = 'outcome-badge' + (badgeClass ? ' ' + badgeClass : '');
    }

    var chain = Promise.resolve();

    function queueSave(triggerEl) {
      var outcome = select.value;
      var reason = reasonInput.value;

      if (window.JOBFIT_PUBLIC_MODE) {
        JobFitStorage.updateHistoryOutcome(entryId, outcome, reason);
        applyBadge(outcome);
        select.dataset.savedValue = outcome;
        reasonInput.dataset.savedValue = reason;
        errorEl.hidden = true;

        // 匿名の利用統計（結果の種類とスコアのみ。内容は一切送らない）。
        // 「未定」に戻した場合は送らない。
        if (outcome) {
          var telemetryData = new FormData();
          telemetryData.append('outcome', outcome);
          telemetryData.append('fit_score', control.dataset.fitScore);
          postAjax('/telemetry/outcome', telemetryData).catch(function () {});
        }
        return;
      }

      // 保存は直列化する（同時に2件飛ばさない）。送信する値はキュー投入時点
      // （change/blur発火時点）でキャプチャする。保存中の失敗リセットが後続の
      // キュー済みリクエストの値を上書きしてしまわないようにするため。
      chain = chain.then(function () {
        var formData = new FormData();
        formData.append('outcome', outcome);
        formData.append('reason', reason);

        return postAjax('/history/' + entryId + '/outcome', formData)
          .then(function (res) {
            if (!res.ok) throw new Error('save failed');
            applyBadge(outcome);
            select.dataset.savedValue = outcome;
            reasonInput.dataset.savedValue = reason;
            errorEl.hidden = true;
          })
          .catch(function () {
            // 失敗した保存を引き起こした側のフィールドだけ戻す。もう一方が
            // 未送信の入力中の値を持っている場合、それを消してしまわないため。
            triggerEl.value = triggerEl.dataset.savedValue;
            errorEl.hidden = false;
          });
      });
    }

    select.addEventListener('change', function () {
      queueSave(select);
    });
    reasonInput.addEventListener('blur', function () {
      if (reasonInput.value !== reasonInput.dataset.savedValue) queueSave(reasonInput);
    });
  });

  if (window.JOBFIT_PUBLIC_MODE) {
    container.querySelectorAll('.sort-toggle a[data-sort]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        var params = paramsFromLocation();
        params.page = 1;
        params.sort = a.dataset.sort;
        renderHistoryFragment(params);
      });
    });
    container.querySelectorAll('.pagination a[data-page]').forEach(function (a) {
      if (a.classList.contains('disabled')) return;
      a.addEventListener('click', function (e) {
        e.preventDefault();
        var params = paramsFromLocation();
        params.page = a.dataset.page;
        renderHistoryFragment(params);
      });
    });
    var searchForm = container.querySelector('.history-search');
    if (searchForm) {
      searchForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var formData = new FormData(searchForm);
        renderHistoryFragment({
          page: 1,
          sort: formData.get('sort'),
          q: formData.get('q'),
          outcome: formData.getAll('outcome'),
          score_min: formData.get('score_min'),
          score_max: formData.get('score_max'),
        });
      });
    }
  }
}

// サーバーとやり取りする絞り込み条件のうち、単一値のフィールド名
// （outcomeだけは複数値なので別扱い）。
var HISTORY_SINGLE_VALUE_FIELDS = ['q', 'score_min', 'score_max'];

// 履歴一覧のURL(?page=&sort=&q=&outcome=&score_min=&score_max=)から
// 現在の絞り込み条件を読み取る。PUBLIC_MODEでのソート/ページ送りクリック時に、
// 検索条件を引き継ぐために使う。
function paramsFromLocation() {
  var params = new URLSearchParams(location.search);
  var result = {
    page: params.get('page') || 1,
    sort: params.get('sort') || 'date',
    outcome: params.getAll('outcome'),
  };
  HISTORY_SINGLE_VALUE_FIELDS.forEach(function (key) {
    result[key] = params.get(key) || '';
  });
  return result;
}

// PUBLIC_MODEでのみ使う。ブラウザに保存された履歴を/history/renderに送り、
// 返ってきたHTML断片で#history-contentを差し替える。
function renderHistoryFragment(params) {
  var formData = new FormData();
  formData.append('history_json', JSON.stringify(JobFitStorage.getHistory()));
  formData.append('page', params.page);
  formData.append('sort', params.sort);
  HISTORY_SINGLE_VALUE_FIELDS.forEach(function (key) {
    formData.append(key, params[key] || '');
  });
  (params.outcome || []).forEach(function (o) {
    formData.append('outcome', o);
  });

  return postAjax('/history/render', formData)
    .then(function (res) {
      if (!res.ok) throw new Error('history render failed: ' + res.status);
      return res.text();
    })
    .then(function (html) {
      var container = document.getElementById('history-content');
      container.innerHTML = html;
      wireHistoryContent(container);
      var url = new URL(location.href);
      url.searchParams.set('page', params.page);
      url.searchParams.set('sort', params.sort);
      HISTORY_SINGLE_VALUE_FIELDS.forEach(function (key) {
        if (params[key]) {
          url.searchParams.set(key, params[key]);
        } else {
          url.searchParams.delete(key);
        }
      });
      url.searchParams.delete('outcome');
      (params.outcome || []).forEach(function (o) {
        url.searchParams.append('outcome', o);
      });
      history.replaceState(null, '', url.pathname + url.search);
    })
    .catch(function () {
      var container = document.getElementById('history-content');
      container.innerHTML = '<p class="notice notice-error">履歴の表示に失敗しました。再読み込みしてください。</p>';
    });
}
