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
        renderHistoryFragment(1, a.dataset.sort);
      });
    });
    container.querySelectorAll('.pagination a[data-page]').forEach(function (a) {
      if (a.classList.contains('disabled')) return;
      a.addEventListener('click', function (e) {
        e.preventDefault();
        var currentSort = new URLSearchParams(location.search).get('sort') || 'date';
        renderHistoryFragment(a.dataset.page, currentSort);
      });
    });
  }
}

// PUBLIC_MODEでのみ使う。ブラウザに保存された履歴を/history/renderに送り、
// 返ってきたHTML断片で#history-contentを差し替える。
function renderHistoryFragment(page, sort) {
  var formData = new FormData();
  formData.append('history_json', JSON.stringify(JobFitStorage.getHistory()));
  formData.append('page', page);
  formData.append('sort', sort);

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
      url.searchParams.set('page', page);
      url.searchParams.set('sort', sort);
      history.replaceState(null, '', url.pathname + url.search);
    })
    .catch(function () {
      var container = document.getElementById('history-content');
      container.innerHTML = '<p class="notice notice-error">履歴の表示に失敗しました。再読み込みしてください。</p>';
    });
}
