/* T&A Abriss & Rückbau – gemeinsames Skript für alle Seiten (mit defer geladen).
   Jede Funktion läuft nur, wenn ihre Elemente auf der Seite vorhanden sind. */
(function(){
  'use strict';
  var $ = function(sel, root){ return (root || document).querySelector(sel); };
  var $$ = function(sel, root){ return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* Nächster möglicher Besichtigungstermin: #slot, alle [data-slot] und #wunsch */
  (function(){
    var slot = document.getElementById('slot'), extra = $$('[data-slot]'), wunsch = document.getElementById('wunsch');
    if (!slot && !extra.length && !wunsch) return;
    var days = ['Sonntag','Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag'];
    var t = new Date(Date.now() + 60 * 60000), s = null;
    for (var i = 0; i < 14 && !s; i++){
      var d = new Date(t.getFullYear(), t.getMonth(), t.getDate() + i), wd = d.getDay(), o = null, c = null;
      if (wd >= 1 && wd <= 5){ o = [16,30]; c = [19,0]; } else if (wd === 6){ o = [9,0]; c = [15,0]; }
      if (!o) continue;
      var a = new Date(d); a.setHours(o[0], o[1], 0, 0); var b = new Date(d); b.setHours(c[0], c[1], 0, 0);
      if (i === 0 && t > a){ a = new Date(t); a.setMinutes(a.getMinutes() <= 30 ? 30 : 60, 0, 0); }
      if (a <= b) s = a;
    }
    if (!s) return;
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var diff = Math.round((new Date(s.getFullYear(), s.getMonth(), s.getDate()) - today) / 864e5);
    var label = (diff === 0 ? 'Heute' : diff === 1 ? 'Morgen' : days[s.getDay()]) + ', ' + s.getHours() + ':' + String(s.getMinutes()).padStart(2, '0') + ' Uhr';
    if (slot) slot.textContent = label;
    extra.forEach(function(el){ el.textContent = label; });
    if (wunsch) wunsch.value = label;
  })();

  /* Anfrageformular: öffnet das E-Mail-Programm mit vorbereiteter Nachricht */
  (function(){
    var f = document.getElementById('f'), err = document.getElementById('err'), ok = document.getElementById('ok');
    if (!f) return;
    function el(id){ return document.getElementById(id); }
    function v(id){ var e = el(id); return e ? (e.value || '').trim() : ''; }
    function valid(){
      var bad = null;
      ['name','tel'].forEach(function(id){
        var e = el(id); if (!e) return;
        var empty = !e.value.trim();
        e.setAttribute('aria-invalid', empty ? 'true' : 'false');
        if (empty && !bad) bad = e;
      });
      if (err) err.hidden = !bad;
      if (bad) bad.focus();
      return !bad;
    }
    function msg(){
      var page = (f.getAttribute('data-page') || '').trim();
      return 'Hallo T&A Abriss & Rückbau, ich möchte eine Besichtigung anfragen.\n\nName: ' + v('name') +
        '\nTelefon: ' + v('tel') + '\nOrt: ' + (v('ort') || '-') + '\nLeistung: ' + v('art') +
        (v('besichtigung') ? '\nBesichtigung: ' + v('besichtigung') : '') +
        '\nWunschtermin: ' + (v('wunsch') || '-') + (page ? '\nSeite: ' + page : '') +
        (v('text') ? '\n\n' + v('text') : '');
    }
    var copy = el('copy'), copied = el('copied');
    if (copy) copy.addEventListener('click', function(){
      var text = msg(), done = function(){ if (copied) copied.hidden = false; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function(){ fallback(text); done(); });
      } else { fallback(text); done(); }
    });
    function fallback(text){
      var ta = document.createElement('textarea'); ta.value = text; ta.setAttribute('readonly', '');
      ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta);
      ta.select(); try { document.execCommand('copy'); } catch (x) {} document.body.removeChild(ta);
    }
    var wa = el('wa');
    if (wa) wa.addEventListener('click', function(){
      if (!valid()) return;
      window.open('https://wa.me/4917632896617?text=' + encodeURIComponent(msg()), '_blank', 'noopener');
    });
    f.addEventListener('submit', function(e){
      e.preventDefault();
      if (!valid()) return;
      if (ok) { ok.hidden = false; ok.scrollIntoView({block: 'nearest'}); }
      location.href = 'mailto:info@ta-abriss-hamburg.de?subject=' + encodeURIComponent(['Anfrage Besichtigung', (f.getAttribute('data-page') || '').trim()].filter(Boolean).join(' – ')) + '&body=' + encodeURIComponent(msg());
    });
  })();

  /* Schnellkontakt (.fab: Handy = Leiste „Anrufen“ + „Anfrage“, PC = Anfrage-Knopf):
     sichtbar nach dem Hero, aus am Kontaktbereich */
  (function(){
    var fab = $('.fab'), hero = $('.hero, .subhero'), contact = document.getElementById('anfrage'), tick = false;
    if (!fab || !hero) return;
    function sync(){
      var past = hero.getBoundingClientRect().bottom < 0;
      var atForm = contact ? contact.getBoundingClientRect().top < innerHeight * 0.6 : false;
      fab.classList.toggle('on', past && !atForm);
    }
    addEventListener('scroll', function(){ if (!tick){ tick = true; requestAnimationFrame(function(){ sync(); tick = false; }); } }, {passive: true});
    addEventListener('resize', sync);
    sync();
  })();

  /* Menü mit drei Strichen */
  (function(){
    var btn = $('.burger[aria-controls="menu"]'), menu = document.getElementById('menu'), header = $('header.top');
    if (!btn || !menu) return;
    var root = document.documentElement, scrim = null, isOpen = false;

    function place(){
      var hb = header ? header.getBoundingClientRect().bottom : btn.getBoundingClientRect().bottom + 12;
      root.style.setProperty('--menu-top', Math.max(0, Math.round(hb)) + 'px');
      var right = Math.max(16, Math.round(innerWidth - btn.getBoundingClientRect().right));
      root.style.setProperty('--menu-right', right + 'px');
    }
    function links(){ return $$('a[href], button:not([disabled])', menu).filter(function(a){ return a.offsetParent !== null || a.getClientRects().length; }); }
    function open(){
      if (isOpen) return;
      isOpen = true;
      place();
      menu.classList.add('open');
      root.classList.add('menu-open');
      btn.setAttribute('aria-expanded', 'true');
      btn.setAttribute('aria-label', 'Menü schließen');
      if (!scrim){ scrim = document.createElement('div'); scrim.className = 'scrim'; scrim.setAttribute('aria-hidden', 'true'); }
      document.body.appendChild(scrim);
      menu.scrollTop = 0;
      var first = links()[0];
      if (first) first.focus({preventScroll: true});
    }
    function close(refocus){
      if (!isOpen) return;
      isOpen = false;
      menu.classList.remove('open');
      root.classList.remove('menu-open');
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('aria-label', 'Menü öffnen');
      if (scrim && scrim.parentNode) scrim.parentNode.removeChild(scrim);
      if (refocus) btn.focus({preventScroll: true});
    }

    btn.addEventListener('click', function(){ isOpen ? close(true) : open(); });
    menu.addEventListener('click', function(e){
      var a = e.target.closest ? e.target.closest('a[href]') : null;
      if (a) close(false);
    });
    document.addEventListener('click', function(e){
      if (!isOpen || menu.contains(e.target) || btn.contains(e.target)) return;
      var ae = document.activeElement;
      close(!ae || ae === document.body || menu.contains(ae));
    });
    document.addEventListener('keydown', function(e){
      if (!isOpen) return;
      if (e.key === 'Escape' || e.key === 'Esc'){ e.preventDefault(); close(true); return; }
      if (e.key !== 'Tab') return;
      /* Fokus bleibt zwischen Knopf und Menü, solange es offen ist */
      var items = links(); if (!items.length) return;
      var first = items[0], last = items[items.length - 1], ae = document.activeElement;
      if (!e.shiftKey && ae === last){ e.preventDefault(); btn.focus(); }
      else if (!e.shiftKey && ae === btn){ e.preventDefault(); first.focus(); }
      else if (e.shiftKey && ae === first){ e.preventDefault(); btn.focus(); }
      else if (e.shiftKey && ae === btn){ e.preventDefault(); last.focus(); }
      else if (!menu.contains(ae) && ae !== btn){ e.preventDefault(); first.focus(); }
    });
    addEventListener('resize', function(){ if (isOpen) place(); });
  })();

  /* Richtpreis-Rechner auf Leistungsseiten (Zahlen aus src/preise.json, nur bei Preisen pro m²).
     Ohne Skript bleibt der Rechner verborgen und die Preistabelle daneben zeigt alle Richtpreise. */
  (function(){
    var box = $('[data-rechner]');
    if (!box) return;
    var rows;
    try { rows = JSON.parse(box.getAttribute('data-rechner')); } catch (e) { return; }
    var sel = $('#rp-pos', box), input = $('#rp-flaeche', box), wrap = $('.rp-flaeche', box), out = $('#rp-out', box);
    if (!rows || !rows.length || !input || !wrap || !out) return;
    var lab = $('span', wrap), cta = $('[data-rp-cta]'), touched = false, summary = '';
    var nf = new Intl.NumberFormat('de-DE', {maximumFractionDigits: 2});
    var nf0 = new Intl.NumberFormat('de-DE', {maximumFractionDigits: 0});
    function eur(n){ return nf0.format(Math.round(n)) + ' €'; }
    function price(a, b){ return b && Math.round(b) > Math.round(a) ? nf0.format(Math.round(a)) + ' – ' + eur(b) : 'ab ' + eur(a); }
    function area(){
      var v = (input.value || '').replace(/\s/g, '').replace(',', '.');
      if (!/^\d+(\.\d+)?$/.test(v)) return null;
      var n = parseFloat(v);
      return n > 0 && n <= 100000 ? n : null;
    }
    function show(sub, main){
      out.textContent = '';
      var s = document.createElement('span'); s.textContent = sub; out.appendChild(s);
      if (main){ var b = document.createElement('strong'); b.textContent = main; out.appendChild(b); }
    }
    function render(){
      var r = rows[sel ? +sel.value : 0] || rows[0];
      if (r.einheit !== 'm2'){
        wrap.hidden = true;
        var t = price(r.ab, r.bis);
        show('Richtpreis für ' + r.name, t);
        summary = r.name + '. Richtpreis auf der Website: ' + t + '.';
        return;
      }
      wrap.hidden = false;
      var fl = r.flaeche || 'Fläche', a = area();
      if (lab) lab.textContent = fl + ' in m²';
      if (a === null){
        show(input.value.trim() ? 'Bitte die Fläche als Zahl eingeben, z. B. 80.' : 'Geben Sie die ' + fl + ' ein, dann steht hier der Richtpreis.', '');
        summary = '';
        return;
      }
      var min = r.mindestens || 0, lo = Math.max(r.ab * a, min), hi = r.bis ? Math.max(r.bis * a, min) : 0;
      var p = price(lo, hi);
      if (p.indexOf('ab ') !== 0) p = 'ca. ' + p;
      show('Richtpreis für ' + nf.format(a) + ' m² ' + fl, p);
      summary = r.name + ', ca. ' + nf.format(a) + ' m² ' + fl + '. Richtpreis auf der Website: ' + p + '.';
    }
    function change(){ touched = true; render(); }
    if (sel) sel.addEventListener('change', change);
    input.addEventListener('input', change);
    /* „Festpreis anfragen“: Angaben aus dem Rechner ins leere Nachrichtenfeld übernehmen */
    if (cta) cta.addEventListener('click', function(){
      var t = document.getElementById('text');
      if (touched && summary && t && !t.value.trim()) t.value = summary.replace(/\u00a0/g, ' ') + '\n';
    });
    box.hidden = false;
    render();
  })();
})();
