import { createApiClient } from "/webapp/api-client.js";
import { createCloudStorage } from "/webapp/cloud-storage.js";
import {
  analyzeQuery,
  assessCollection,
  assessDraft,
  createDraftSnapshot,
  escapeHtml,
  parseDraftSnapshot,
  pluralize,
  safeHttpUrl,
} from "/webapp/studio-core.js";

(function () {
  const tg = window.Telegram?.WebApp || {
    initData: "", initDataUnsafe: {}, colorScheme: "dark",
    ready(){}, expand(){}, close(){}, setHeaderColor(){}, setBackgroundColor(){},
    BackButton: { show(){}, hide(){}, onClick(){} },
    CloudStorage: {
      getItem(key, cb){ try { cb(null, localStorage.getItem(key)); } catch(e) { cb(e); } },
      setItem(key, value, cb){ try { localStorage.setItem(key, value); if (cb) cb(null, true); } catch(e) { if (cb) cb(e); } },
    },
  };
  const cloud = createCloudStorage(tg.CloudStorage);
  tg.ready(); tg.expand();

  const EN = !((tg.initDataUnsafe?.user?.language_code || "ru").match(/^(ru|uk|be|kk)/));
  const T = EN ? {
    ph: "A link or a name…", recent: "RECENT", popular: "POPULAR QUERIES",
    hint: "A link, title or several tracks — Studio recognizes the flow automatically.",
    loading: "SEARCHING…", found: "found", release1: "release", release2: "releases",
    nf: "Release not found", nfSub: "Try another name", retry: "Try again",
    previewTitle: "Post preview", format: "Style", apply: "Apply",
    send: "Send to me", publish: "Publish", sent: "Sent", published: "Published!",
    undo: "Undo", undone: "POST DELETED", scheduled: "SCHEDULED: ",
    dupA: "⚠️ Already published on ", dupB: ". Publish again?", confirm: "Publish", cancel: "Cancel",
    err: "The signal got noisy. Try again.", network: "No connection. Check your internet and retry.", timeout: "The server needs more time. Try again.", busy: "Still working on it. Try again in a moment.", allPlatforms: "All",
    toCrate: "In crate", crateFull: "CRATE IS FULL",
    secContent: "Content", secText: "Your text", secTags: "Hashtags", secPm: "Platforms & order",
    rHashtags: "Hashtags", rQuote: "Quote / CTA", rPhoto: "Photo mode (no player)", rBig: "Large preview",
    addTrack: "Add track", crateEmpty: "ADD TRACKS FROM ANY CARD", needMore: "ADD AT LEAST 2 TRACKS",
    crateSend: "Send to me", cratePublish: "Publish collection", crateClear: "Clear crate", crateShare: "Share collection",
    crateTitle: "tracks", queueTitle: "posts", queueEmpty: "QUEUE IS EMPTY",
    topUsers: "TOP USERS", topChats: "TOP CHATS", posted: "in channel",
    sheetTitle: "When to publish?", in1h: "In 1 hour", in3h: "In 3 hours", tonight: "Tonight 19:00", tomorrow: "Tomorrow 10:00",
    clipQ: "Paste from clipboard?", preview30: "0:30 preview", addTag: "add",
    stat: { posts: "posts", song: "tracks", album: "albums", podcast: "podcasts", videos: "videos", collections: "sets" },
    coach: [["🔎","Find the release","Paste a link or search by artist and title."],["🎧","Check the sound","Preview the track before you build the post."],["🎛","Shape the card","Tune the text, cover and platforms in Style."],["📡","Choose a destination","Send to yourself, a channel or the publishing queue."]],
    gotIt: "Start creating", next: "Next", skip: "Skip", step: "STEP",
    flow: ["Find","Style","Send"], support: "All music platforms", batch: "Several links → crate",
    quick: { create:["Create","Smart release search"], crate:["Crate","Build a set"], inline:["Inline search","In any chat"], queue:["Queue","Publishing plan"], stats:["Analytics","Channel pulse"] },
    readyCover: "Artwork", readyNoCover: "No artwork", readyHashtags: "Hashtags", readyClean: "Clean text", readyPlatforms: "platforms",
    ui: {
      heroKicker:"MUSIC POST WORKSHOP", heroTitle:"Build a post,<br><em>that sounds.</em>",
      homeError:"Could not refresh", homeErrorCopy:"Check your connection and retry", loadError:"Could not load data", retry:"Retry",
      cancelSearch:"Cancel search", notFoundHead:"Nothing found", notFoundTitle:"Release not found", notFoundCopy:"Refine the artist and title or paste a direct link", editQuery:"Edit query",
      resultKicker:"READY TO AIR", resultCopy:"This is what your audience will see", format:"Style", livePreview:"LIVE PREVIEW", ctaPlaceholder:"Add your own caption…", publishedStamp:"PUBLISHED", sentStamp:"SENT",
      saved:"Saved", saving:"Saving…", saveError:"Not saved", onePlatform:"Keep at least one platform", done:"Done", content:"Content", ownText:"Your text", hashtags:"Hashtags", platforms:"Platforms & order",
      crate:"Crate", crateKicker:"CURATED BY STONERHAND", crateHero:"Your next set", queue:"Queue", stats:"Analytics", period:"All time", breakdown:"Breakdown", create:"Create",
      close:"Close", publishKicker:"FINAL STEP", publishTitle:"Where should the post go?",
      destinations:[["To channel","Publish for everyone"],["Send to me","Check in your private chat"],["Add to queue","Choose a date and time"],["Send to another chat","Ready post with every button"]],
      successNext:"Create another", successClose:"Back to the post",
    },
    shareTitle: "Share where?", shareAll: "All platforms",
    shareKicker: "READY POST", sharePost: "Send post with buttons",
    sharePostCopy: "Choose a Telegram chat, group or channel",
    sharePreparing: "Preparing post…", shareFailed: "Could not open sharing. Try again.",
    shareLinks: "OR SHARE A LINK",
    presets: "Presets", presetSave: "save", presetEmpty: "Save the current look to reuse it",
    presetName: "Preset", reschedule: "Reschedule",
    queueEmptyT: "Queue is empty", queueEmptyS: "Scheduled posts will show up here",
    statsEmptyT: "No stats yet", statsEmptyS: "Numbers appear once you start posting",
    nowPlaying: "Preview", confirmRemove: "Remove this item?", confirmClear: "Clear the whole crate?",
    crateEdit: "Style", crateEditor: "Collection editor", crateSave: "Save collection",
    continueAction: "Continue",
    crateTitleLabel: "Title", crateIntroLabel: "Introduction", crateOutroLabel: "Closing line", crateTagsLabel: "Hashtags",
    crateItemEditor: "Track details", crateSection: "Group", crateNote: "Comment", crateItemSave: "Save track",
    tagRecommended: "RECOMMENDED", tagHealthy: "Good set: clear and relevant", tagTooMany: "Keep up to 6–8 focused tags",
  } : {
    ph: "Ссылка или название…", recent: "НЕДАВНИЕ", popular: "ПОПУЛЯРНЫЕ ЗАПРОСЫ",
    hint: "Ссылка, название или несколько треков — Студия распознает сценарий сама.",
    loading: "ИЩЕМ РЕЛИЗ…", found: "Найдено", release1: "релиз", release2: "релиза",
    nf: "Релиз не найден", nfSub: "Попробуй другое название", retry: "Попробовать снова",
    previewTitle: "Превью поста", format: "Оформление", apply: "Применить",
    send: "Отправить себе", publish: "Опубликовать", sent: "Отправлено", published: "Опубликовано!",
    undo: "Отмена", undone: "ПОСТ УДАЛЁН", scheduled: "В ОЧЕРЕДИ: ",
    dupA: "⚠️ Уже публиковалось ", dupB: ". Опубликовать снова?", confirm: "Опубликовать", cancel: "Отмена",
    err: "Связь зашумела. Попробуем ещё раз.", network: "Нет соединения. Проверь интернет и повтори.", timeout: "Серверу нужно больше времени. Попробуй ещё раз.", busy: "Ещё работаем над запросом. Повтори через секунду.", allPlatforms: "Все",
    toCrate: "В подборке", crateFull: "ПОДБОРКА ЗАПОЛНЕНА",
    secContent: "Содержимое", secText: "Свой текст", secTags: "Хэштеги", secPm: "Платформы и порядок",
    rHashtags: "Хэштеги", rQuote: "Цитата / CTA", rPhoto: "Фото-режим (без плеера)", rBig: "Большое превью",
    addTrack: "Добавить трек", crateEmpty: "ДОБАВЛЯЙ ТРЕКИ С ЛЮБОЙ КАРТОЧКИ", needMore: "НУЖНО МИНИМУМ 2 ТРЕКА",
    crateSend: "Отправить себе", cratePublish: "Опубликовать подборку", crateClear: "Очистить подборку", crateShare: "Поделиться подборкой",
    crateTitle: "треков", queueTitle: "постов", queueEmpty: "ОЧЕРЕДЬ ПУСТА",
    topUsers: "ТОП ПОЛЬЗОВАТЕЛЕЙ", topChats: "ТОП ЧАТОВ", posted: "в канале",
    sheetTitle: "Когда опубликовать?", in1h: "Через час", in3h: "Через 3 часа", tonight: "Сегодня 19:00", tomorrow: "Завтра 10:00",
    clipQ: "Вставить из буфера?", preview30: "0:30 превью", addTag: "тег",
    stat: { posts: "постов", song: "треков", album: "альбомов", podcast: "подкастов", videos: "видео", collections: "подборок" },
    coach: [["🔎","Найди точный релиз","Вставь ссылку или найди музыку по артисту и названию."],["🎧","Проверь звучание","Прослушай отрывок до того, как собирать пост."],["🎛","Настрой карточку","Измени текст, обложку и площадки в «Оформлении»."],["📡","Выбери назначение","Отправь себе, опубликуй в канал или поставь в очередь."]],
    gotIt: "Начать", next: "Дальше", skip: "Пропустить", step: "ШАГ",
    flow: ["Найти","Оформить","Отправить"], support: "Все музыкальные сервисы", batch: "Несколько ссылок → подборка",
    quick: { create:["Создать","Умный поиск релиза"], crate:["Подборка","Собрать сет"], inline:["Inline-поиск","В любом чате"], queue:["Очередь","Планы на эфир"], stats:["Статистика","Ритм канала"] },
    readyCover: "Обложка", readyNoCover: "Без обложки", readyHashtags: "Хэштеги", readyClean: "Чистый текст", readyPlatforms: "площадок",
    ui: {
      heroKicker:"МУЗЫКАЛЬНАЯ МАСТЕРСКАЯ", heroTitle:"Собери пост,<br><em>который звучит.</em>",
      homeError:"Не удалось обновить", homeErrorCopy:"Проверь соединение и повтори", loadError:"Не удалось загрузить данные", retry:"Ещё раз",
      cancelSearch:"Отменить поиск", notFoundHead:"Ничего не найдено", notFoundTitle:"Релиз не найден", notFoundCopy:"Уточни исполнителя и название или вставь прямую ссылку", editQuery:"Изменить запрос",
      resultKicker:"ГОТОВО К ЭФИРУ", resultCopy:"Так пост увидит аудитория", format:"Оформление", livePreview:"ЖИВОЕ ПРЕВЬЮ", ctaPlaceholder:"Добавь свой комментарий…", publishedStamp:"ОПУБЛИКОВАНО", sentStamp:"ОТПРАВЛЕНО",
      saved:"Сохранено", saving:"Сохраняю…", saveError:"Не сохранено", onePlatform:"Оставь хотя бы одну площадку", done:"Готово", content:"Содержимое", ownText:"Свой текст", hashtags:"Хэштеги", platforms:"Площадки и порядок",
      crate:"Подборка", crateKicker:"СОБРАНО STONERHAND", crateHero:"Следующий сет", queue:"Очередь", stats:"Статистика", period:"За всё время", breakdown:"Разбивка", create:"Создать",
      close:"Закрыть", publishKicker:"ФИНАЛЬНЫЙ ШАГ", publishTitle:"Куда отправить пост?",
      destinations:[["В канал","Опубликовать для всех"],["Отправить себе","Проверить в личном чате"],["Добавить в очередь","Выбрать дату и время"],["Отправить в другой чат","Готовый пост со всеми кнопками"]],
      successNext:"Создать следующий", successClose:"Вернуться к посту",
    },
    shareTitle: "Куда поделиться?", shareAll: "Все площадки",
    shareKicker: "ГОТОВЫЙ ПОСТ", sharePost: "Отправить пост с кнопками",
    sharePostCopy: "Выбрать чат, группу или канал в Telegram",
    sharePreparing: "Готовим пост…", shareFailed: "Не удалось открыть отправку. Попробуй ещё раз.",
    shareLinks: "ИЛИ ПОДЕЛИТЬСЯ ССЫЛКОЙ",
    presets: "Пресеты", presetSave: "сохранить", presetEmpty: "Сохрани текущее оформление, чтобы применять в один тап",
    presetName: "Пресет", reschedule: "Перенести",
    queueEmptyT: "Очередь пуста", queueEmptyS: "Отложенные посты появятся здесь",
    statsEmptyT: "Пока нет статистики", statsEmptyS: "Цифры появятся, как начнёшь постить",
    nowPlaying: "Превью", confirmRemove: "Удалить этот элемент?", confirmClear: "Очистить всю подборку?",
    crateEdit: "Оформить", crateEditor: "Редактор подборки", crateSave: "Сохранить оформление",
    continueAction: "Продолжить",
    crateTitleLabel: "Название", crateIntroLabel: "Вступление", crateOutroLabel: "Финальная фраза", crateTagsLabel: "Хэштеги",
    crateItemEditor: "Настройка трека", crateSection: "Группа", crateNote: "Комментарий", crateItemSave: "Сохранить трек",
    tagRecommended: "РЕКОМЕНДУЕМ", tagHealthy: "Хороший набор: понятно и по теме", tagTooMany: "Лучше оставить 6–8 точных тегов",
  };

  const SUGGESTIONS = ["Black Sabbath – Paranoid","Sleep – Dragonaut","Electric Wizard – Funeralopolis","Kyuss – Green Machine"];
  const PLATFORM_META = {
    spotify:{color:"#1DB954",letter:"●",name:"Spotify"}, appleMusic:{color:"#FA2D48",letter:"♪",name:"Apple Music"},
    applePodcasts:{color:"#B150E2",letter:"◉",name:"Podcasts"}, youtubeMusic:{color:"#FF0000",letter:"▶",name:"YouTube"},
    soundcloud:{color:"#FF5500",letter:"☁",name:"SoundCloud"}, deezer:{color:"#A238FF",letter:"≋",name:"Deezer"},
    tidal:{color:"#3EB3E7",letter:"◆",name:"Tidal"}, yandexMusic:{color:"#FC3F1D",letter:"Я",name:EN?"Yandex":"Яндекс"},
  };
  const PREFLIGHT = EN ? {
    draft: {
      platforms:(n)=>n+" platforms connected", noPlatforms:"Choose at least one platform",
      textReady:"Caption is ready", noText:"Add a short caption",
      artworkReady:"Artwork is ready", noArtwork:"No artwork — text mode will be used",
      cleanText:"Clean text without tags", tagsReady:(n)=>n+" focused hashtags", tooManyTags:"Too many hashtags",
    },
    collection: {
      tracks:(n)=>n+" tracks in the set", needTracks:"Add at least two tracks",
      titleReady:"Collection has a title", noTitle:"Add a memorable title",
      notesReady:"Track notes added", noNotes:"Add context to at least one track",
    },
  } : {
    draft: {
      platforms:(n)=>"Подключено площадок: "+n, noPlatforms:"Выбери хотя бы одну площадку",
      textReady:"Подводка готова", noText:"Добавь короткую подводку",
      artworkReady:"Обложка готова", noArtwork:"Без обложки — будет текстовый режим",
      cleanText:"Чистый текст без тегов", tagsReady:(n)=>"Точных хэштегов: "+n, tooManyTags:"Слишком много хэштегов",
    },
    collection: {
      tracks:(n)=>"Треков в сете: "+n, needTracks:"Добавь минимум два трека",
      titleReady:"У подборки есть название", noTitle:"Добавь запоминающееся название",
      notesReady:"Есть комментарии к трекам", noNotes:"Добавь контекст хотя бы к одному треку",
    },
  };

  const $ = (id) => document.getElementById(id);
  const VIEWS = ["home","candidates","loading","notfound","result","format","crate","queue","stats"];
  const TAB_SCREENS = ["home","crate","queue","stats"];
  let state = null, isAdmin = false, playingBtn = null, syncTimer = null, undoTimer = null;
  let historyItems = [], crateItems = [], crateCount = 0;
  let collectionMeta = { title:"", intro:"", outro:"", tags:[] }, editingCrateIndex = -1, publishMode = "draft";
  let navStack = ["home"];
  let loadSeq = 0, syncSeq = 0, previewFetching = false, lastQuery = "";
  const apiTransport = createApiClient({
    getInitData: () => tg.initData,
    onUnauthorized: authExpired,
  });

  const hap = {
    tap(){try{tg.HapticFeedback.impactOccurred("light")}catch(e){}},
    medium(){try{tg.HapticFeedback.impactOccurred("medium")}catch(e){}},
    pick(){try{tg.HapticFeedback.selectionChanged()}catch(e){}},
    ok(){try{tg.HapticFeedback.notificationOccurred("success")}catch(e){}},
    warn(){try{tg.HapticFeedback.notificationOccurred("warning")}catch(e){}},
    err(){try{tg.HapticFeedback.notificationOccurred("error")}catch(e){}},
  };
  const esc = escapeHtml;
  function plural(n, enOne, enMany, ruOne, ruFew, ruMany) {
    return pluralize(n, [enOne, enMany], [ruOne, ruFew, ruMany], EN);
  }
  const safeUrl = safeHttpUrl;
  function artHtml(url,emoji,cls){const s=safeUrl(url);return s?'<img class="'+cls+'" alt="" loading="lazy" data-emoji="'+esc(emoji||"🎵")+'" src="'+s+'">':'<div class="'+cls+'">'+esc(emoji||"🎵")+"</div>";}
  // A broken cover must never leave an empty hole: swap it for the emoji tile.
  window.addEventListener("error", (e) => {
    const t = e.target;
    if (!t || t.tagName !== "IMG" || t.dataset.fbk) return;
    t.dataset.fbk = "1";
    if (t.dataset.emoji) {
      const d = document.createElement("div");
      d.className = t.className; d.textContent = t.dataset.emoji;
      t.replaceWith(d);
    } else { t.style.visibility = "hidden"; }
  }, true);
  function ico(n,c){return '<svg class="icon '+(c||"")+'" aria-hidden="true"><use href="#i-'+n+'"/></svg>';}

  /* ── theme ── */
  let dark = (tg.colorScheme || "dark") !== "light";
  let themePinned = false;
  function applyTheme() {
    document.body.classList.toggle("dark", dark);
    document.body.classList.toggle("light", !dark);
    $("theme-btn").innerHTML = ico(dark ? "sun" : "moon", "s16");
    $("theme-btn").setAttribute("aria-label", dark ? (EN?"Use light theme":"Включить светлую тему") : (EN?"Use dark theme":"Включить тёмную тему"));
    const bg = dark ? "#090B11" : "#F3F5FA";
    try { tg.setHeaderColor(bg); tg.setBackgroundColor(bg); } catch (e) {}
    $("dt-input").style.colorScheme = dark ? "dark" : "light";
  }
  $("theme-btn").addEventListener("click", () => { hap.tap(); dark = !dark; themePinned = true; applyTheme(); cloud.set("theme", dark?"d":"l"); });
  cloud.get("theme", (e,v) => { if (v==="l") { dark=false; themePinned=true; } else if (v==="d") { dark=true; themePinned=true; } applyTheme(); });
  try { tg.onEvent?.("themeChanged", () => { if (!themePinned) { dark = tg.colorScheme !== "light"; applyTheme(); } }); } catch(e) {}
  applyTheme();

  /* Telegram can reserve more space than CSS env(safe-area-inset-*),
     especially in fullscreen mode. Keep every fixed control inside it. */
  function syncSafeArea() {
    const inset = tg.contentSafeAreaInset || tg.safeAreaInset || {};
    const root = document.documentElement.style;
    root.setProperty("--tg-safe-top", Math.max(0, Number(inset.top)||0)+"px");
    root.setProperty("--tg-safe-right", Math.max(0, Number(inset.right)||0)+"px");
    root.setProperty("--tg-safe-bottom", Math.max(0, Number(inset.bottom)||0)+"px");
    root.setProperty("--tg-safe-left", Math.max(0, Number(inset.left)||0)+"px");
  }
  syncSafeArea();
  try { tg.onEvent?.("safeAreaChanged", syncSafeArea); tg.onEvent?.("contentSafeAreaChanged", syncSafeArea); tg.onEvent?.("viewportChanged", syncSafeArea); } catch(e) {}

  /* Prefer Telegram's native primary action where it exists. Browsers and
     older clients keep the custom dock, so the flow never loses its CTA. */
  const nativeMain = tg.MainButton && typeof tg.MainButton.show === "function" ? tg.MainButton : null;
  let nativeMainHandler = null;
  function hideNativeMain() {
    document.body.classList.remove("native-main-active");
    if (!nativeMain) return;
    try { if (nativeMainHandler) nativeMain.offClick?.(nativeMainHandler); nativeMainHandler=null; nativeMain.hideProgress?.(); nativeMain.hide(); } catch(e) {}
  }
  function showNativeMain(text, handler) {
    if (!nativeMain) return false;
    try {
      if (nativeMainHandler) nativeMain.offClick?.(nativeMainHandler);
      nativeMainHandler = handler; nativeMain.setText?.(text); nativeMain.enable?.(); nativeMain.onClick?.(handler); nativeMain.show();
      document.body.classList.add("native-main-active");
      return true;
    } catch(e) { document.body.classList.remove("native-main-active"); return false; }
  }
  function setNativeMainBusy(busy) {
    if (!nativeMain) return;
    try { if (busy) { nativeMain.disable?.(); nativeMain.showProgress?.(false); } else { nativeMain.hideProgress?.(); nativeMain.enable?.(); } } catch(e) {}
  }

  /* static texts */
  $("query").placeholder = T.ph;
  $("home-hint").innerHTML = T.hint;
  $("popular-lbl").textContent = T.popular;
  $("loading-lbl").textContent = T.loading;
  $("clip-text").textContent = T.clipQ;
  $("sheet-title").textContent = T.sheetTitle;
  $("fmt-apply").textContent = T.apply;
  $("open-format").lastChild.textContent = T.format;
  $("top-users-lbl").textContent = T.topUsers;
  $("top-chats-lbl").textContent = T.topChats;
  $("toast-cancel").textContent = T.cancel;
  $("t-presets").textContent = T.presets;
  $("t-preset-save").textContent = T.presetSave;
  $("share-title").textContent = T.shareTitle;
  $("share-kicker").textContent = T.shareKicker;
  $("share-post-title").textContent = T.sharePost;
  $("share-post-copy").textContent = T.sharePostCopy;
  $("share-links-label").textContent = T.shareLinks;
  $("flow-find").textContent = T.flow[0];
  $("flow-style").textContent = T.flow[1];
  $("flow-send").textContent = T.flow[2];
  $("support-label").textContent = T.support;
  $("batch-label").textContent = T.batch;
  $("q-create-title").textContent = T.quick.create[0]; $("q-create-sub").textContent = T.quick.create[1];
  $("q-crate-title").textContent = T.quick.crate[0]; $("q-crate-sub").textContent = T.quick.crate[1];
  $("q-inline-title").textContent = T.quick.inline[0]; $("q-inline-sub").textContent = T.quick.inline[1];
  $("q-queue-title").textContent = T.quick.queue[0]; $("q-queue-sub").textContent = T.quick.queue[1];
  $("q-stats-title").textContent = T.quick.stats[0]; $("q-stats-sub").textContent = T.quick.stats[1];
  $("hero-kicker").textContent = T.ui.heroKicker; $("home-title").innerHTML = T.ui.heroTitle;
  $("home-alert-title").textContent = T.ui.homeError; $("home-alert-copy").textContent = T.ui.homeErrorCopy; $("home-retry").textContent = T.ui.retry;
  $("loading-cancel").setAttribute("aria-label", T.ui.cancelSearch);
  $("cand-label").textContent = T.found; $("result-label").textContent = T.previewTitle;
  $("nf-head").textContent = T.ui.notFoundHead; $("nf-title").textContent = T.ui.notFoundTitle; $("nf-copy").textContent = T.ui.notFoundCopy; $("nf-retry").textContent = T.ui.editQuery;
  $("result-kicker").textContent = T.ui.resultKicker; $("result-copy").textContent = T.ui.resultCopy;
  $("format-title").textContent = T.ui.format; $("format-kicker").textContent = T.ui.livePreview; $("fmt-sync").textContent = T.ui.saved;
  $("cta-input").placeholder = T.ui.ctaPlaceholder;
  $("format-content").textContent = T.ui.content; $("format-text").textContent = T.ui.ownText; $("format-tags").textContent = T.ui.hashtags; $("format-platforms").textContent = T.ui.platforms;
  $("crate-label").textContent = T.ui.crate; $("crate-kicker").textContent = T.ui.crateKicker; $("crate-hero-title").textContent = T.ui.crateHero;
  $("crate-edit-label").textContent = T.crateEdit;
  $("crate-editor-title").textContent = T.crateEditor; $("crate-editor-save").textContent = T.crateSave;
  $("crate-title-label").textContent = T.crateTitleLabel; $("crate-intro-label").textContent = T.crateIntroLabel; $("crate-outro-label").textContent = T.crateOutroLabel; $("crate-tags-label").textContent = T.crateTagsLabel;
  $("crate-item-title").textContent = T.crateItemEditor; $("crate-section-label").textContent = T.crateSection; $("crate-note-label").textContent = T.crateNote; $("crate-item-save").textContent = T.crateItemSave;
  $("queue-label").textContent = T.ui.queue; $("stats-title").textContent = T.ui.stats; $("stats-period").textContent = T.ui.period; $("stats-breakdown-label").textContent = T.ui.breakdown;
  $("create-label").textContent = T.ui.create; $("fmt-apply").textContent = T.ui.done;
  $("format-nav-presets").textContent = EN ? "Style" : "Стиль";
  $("format-nav-copy").textContent = EN ? "Copy" : "Текст";
  $("format-nav-tags").textContent = EN ? "Tags" : "Теги";
  $("format-nav-services").textContent = EN ? "Services" : "Сервисы";
  $("result-score-label").textContent = EN ? "ready" : "готово";
  $("queue-intro-title").textContent = EN ? "Broadcast plan" : "План эфира";
  $("queue-intro-copy").textContent = EN ? "Every scheduled publication in one timeline" : "Все запланированные публикации в одном таймлайне";
  $("stats-intro-title").textContent = EN ? "Channel pulse" : "Пульс канала";
  $("stats-intro-copy").textContent = EN ? "The essential numbers without dashboard noise" : "Главные цифры без перегруженного дашборда";
  $("publish-kicker").textContent = T.ui.publishKicker; $("publish-title").textContent = T.ui.publishTitle;
  [["publish-channel",0],["publish-self",1],["publish-later",2],["publish-copy",3]].forEach(([prefix,index]) => { $(prefix+"-title").textContent=T.ui.destinations[index][0]; $(prefix+"-copy").textContent=T.ui.destinations[index][1]; });
  $("success-next").textContent = T.ui.successNext; $("success-close").textContent = T.ui.successClose;
  document.querySelectorAll(".sheet-close").forEach((button) => button.setAttribute("aria-label", T.ui.close));
  document.querySelector('#tabbar [data-tab="home"] span').textContent = EN?"Home":"Главная";
  document.querySelector('#tabbar [data-tab="crate"] span').textContent = EN?"Crate":"Подборка";
  document.querySelector('#tabbar [data-tab="queue"] span').textContent = EN?"Queue":"Очередь";
  document.querySelectorAll("#format-nav button").forEach((button, index) => {
    button.classList.toggle("active", index === 0);
    button.addEventListener("click", () => {
      hap.pick();
      document.querySelectorAll("#format-nav button").forEach((item) => item.classList.toggle("active", item === button));
      const target = $(button.dataset.target);
      const scroller = $("v-format").querySelector(".scroll");
      if (!target || !scroller) return;
      const stickyBottom = $("format-nav").getBoundingClientRect().bottom;
      const targetTop = target.getBoundingClientRect().top;
      scroller.scrollBy({
        top: targetTop - stickyBottom - 12,
        behavior: "smooth",
      });
    });
  });

  SUGGESTIONS.forEach((s, index) => {
    const b = document.createElement("button");
    b.className = "row"; b.style.opacity = "1";
    b.innerHTML = '<div class="row-art">'+ico("music","suggestion-note")+'</div><span class="suggestion-index">'+String(index+1).padStart(2,"0")+'</span><div class="row-meta"><div class="row-title">'+esc(s)+"</div></div>"+ico("cr","s16 suggestion-arrow");
    b.addEventListener("click", () => { $("query").value = s; updateSearchMode(); search(); });
    $("suggestions").appendChild(b);
  });

  /* ── navigation ── */
  function show(view, push) {
    stopAudio(); clearUndo();
    if (view !== "result") hideNativeMain();
    $("typeahead").classList.remove("open");
    VIEWS.forEach((v) => {
      const el = $("v-" + v), active = v === view;
      el.classList.toggle("hidden", !active);
      el.setAttribute("aria-hidden", String(!active));
      if (active) { el.style.animation = "none"; void el.offsetWidth; el.style.animation = ""; }
    });
    $("dock").classList.toggle("on", view === "result");
    const isTab = TAB_SCREENS.includes(view);
    $("tabbar").classList.toggle("on", isTab);
    document.querySelectorAll("#tabbar button").forEach((b) => {
      const active = b.dataset.tab === view;
      b.classList.toggle("active", active);
      if (active) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    if (push !== false && navStack[navStack.length-1] !== view) navStack.push(view);
    if (view === "result" && state) showNativeMain(state.can_publish ? T.publish : T.send, openPublish);
    try { if (view === "home") { navStack = ["home"]; tg.BackButton.hide(); } else tg.BackButton.show(); } catch(e) {}
  }
  try { tg.BackButton.onClick(() => { hap.tap(); goBack(); }); } catch(e) {}
  function goBack() {
    if ($("crate-item-sheet").classList.contains("open")) { closeCrateItemEditor(); return; }
    if ($("crate-editor-sheet").classList.contains("open")) { closeCrateEditor(); return; }
    if ($("publish-sheet").classList.contains("open")) { closePublish(); return; }
    if ($("share-sheet").classList.contains("open")) { closeShare(); return; }
    if ($("sheet").classList.contains("open")) { closeSheet(); return; }
    cancelPending();
    navStack.pop();
    let prev = navStack[navStack.length-1] || "home";
    // never return the user to a transient "loading"/"format" step
    while ((prev === "loading") && navStack.length > 1) { navStack.pop(); prev = navStack[navStack.length-1] || "home"; }
    if (prev === "home") loadHome();
    show(prev, false);
  }
  ["cand-back","nf-back","res-back","fmt-back","crate-back","queue-back","stats-back"].forEach((id) => $(id).addEventListener("click", () => { hap.tap(); goBack(); }));
  $("loading-cancel").addEventListener("click", () => { hap.tap(); goBack(); });
  document.querySelectorAll("#tabbar button").forEach((b) => b.addEventListener("click", () => {
    hap.tap(); cancelPending(); const t = b.dataset.tab;
    if (t === "home") { loadHome(); show("home"); }
    else if (t === "crate") openCrate();
    else if (t === "queue") openQueue();
    else if (t === "stats") openStats();
  }));
  // Home shortcut cards (mirror the tab bar).
  $("q-create").addEventListener("click", () => {
    hap.tap();
    cancelPending();
    show("home");
    requestAnimationFrame(() => $("query").focus());
  });
  $("q-crate").addEventListener("click", () => { hap.tap(); cancelPending(); openCrate(); });
  $("q-inline").addEventListener("click", () => {
    hap.tap();
    try { tg.switchInlineQuery("", ["users","groups","channels"]); }
    catch(e) { try { tg.switchInlineQuery(""); } catch(x) { flash(EN?"Inline mode is unavailable":"Inline-режим недоступен"); } }
  });
  $("q-queue").addEventListener("click", () => { hap.tap(); cancelPending(); openQueue(); });
  $("q-stats").addEventListener("click", () => { hap.tap(); cancelPending(); openStats(); });
  $("admin-tools").addEventListener("click", () => { hap.tap(); cancelPending(); openStats(); });
  $("create-tab").addEventListener("click", () => { hap.tap(); cancelPending(); loadHome(); show("home"); setTimeout(()=>$("query").focus(),80); });

  // Every request is bounded: a hung or ice-cold serverless call can never
  // freeze the UI. Requests flagged `abortable` are cancelled the moment the
  // user navigates away, so "back" is always instant.
  async function api(action, payload, opts) {
    return apiTransport.request(action, payload, opts);
  }
  // Small transient toast for non-blocking notices (rate limits, soft errors).
  function flash(msg) {
    let el = document.getElementById("flash");
    if (!el) {
      el = document.createElement("div"); el.id = "flash"; el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite");
      el.style.cssText = "position:fixed;left:50%;bottom:88px;transform:translateX(-50%);z-index:9998;max-width:82%;padding:10px 18px;border-radius:12px;background:var(--card);border:1px solid var(--border);color:var(--fg);font-size:13px;line-height:1.4;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.3);opacity:0;transition:opacity .2s";
      document.body.appendChild(el);
    }
    el.textContent = msg; el.style.opacity = "1";
    clearTimeout(el._t); el._t = setTimeout(() => { el.style.opacity = "0"; }, 2400);
  }
  function errorText(error) {
    if (error === "network") return T.network;
    if (error === "timeout") return T.timeout;
    if (error === "request_in_progress" || error === "queue_busy") return T.busy;
    if (error === "draft not found") return EN?"This draft expired. Find the release again.":"Черновик устарел. Найди релиз ещё раз.";
    if (error === "need more tracks") return T.needMore;
    if (error === "unauthorized") return EN?"Reopen Studio from the bot.":"Закрой и снова открой Студию из бота.";
    if (error === "save_failed") return EN?"Changes were not saved. Check the connection and retry.":"Изменения не сохранены. Проверь соединение и повтори.";
    return T.err;
  }
  function confirmAction(message) {
    return new Promise((resolve) => {
      try {
        if (typeof tg.showConfirm === "function") { tg.showConfirm(message, resolve); return; }
      } catch (e) {}
      resolve(typeof globalThis.confirm === "function" ? globalThis.confirm(message) : true);
    });
  }
  function setToastOpen(open) {
    $("toast").classList.toggle("on", open);
    $("toast").setAttribute("aria-hidden", String(!open));
  }
  function cancelPending() {
    loadSeq++;
    apiTransport.cancelPending();
  }
  function loadPrefs(cb){ cloud.get("prefs",(e,v)=>{let p=null;try{p=v?JSON.parse(v):null}catch(x){}cb(p)}); }
  function savePrefs(p){ cloud.set("prefs",JSON.stringify(p)); }
  // When Telegram's signed initData expires (Studio left open for hours), every
  // request 401s — tell the user plainly instead of failing silently.
  let authGone = false;
  function authExpired() {
    if (authGone) return; authGone = true;
    try { hap.err(); } catch(e) {}
    const el = document.createElement("div");
    el.style.cssText = "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;padding:32px;text-align:center;background:var(--bg)";
    el.innerHTML = '<div style="max-width:280px"><div style="font-size:40px;margin-bottom:14px">🔒</div>'+
      '<div style="font-family:\'Unbounded\',\'Golos Text\',sans-serif;font-size:17px;margin-bottom:8px">'+(EN?"Session expired":"Сессия истекла")+'</div>'+
      '<div style="color:var(--muted);font-size:14px;line-height:1.5;margin-bottom:20px">'+(EN?"Reopen the Studio to keep working.":"Переоткрой Студию, чтобы продолжить.")+'</div>'+
      '<button style="padding:12px 28px;border-radius:12px;border:none;background:var(--primary);color:#fff;font:inherit;font-size:14px">'+(EN?"Close":"Закрыть")+'</button></div>';
    document.body.appendChild(el);
    el.querySelector("button").addEventListener("click", () => { try { tg.close(); } catch(e) { location.reload(); } });
  }

  /* ── audio ── */
  const player = $("player");
  // A dead preview URL must not leave the player stuck "playing".
  player.addEventListener("error", () => { if (player.src) { stopAudio(); hap.err(); } });
  function stopAudio() {
    player.pause(); player.removeAttribute("src"); player.onended = null;
    if (playingBtn) { playingBtn = null; }
    const eq = $("card-eq"); if (eq) eq.classList.remove("on");
    document.querySelectorAll(".play-btn svg").forEach(refreshPlayIcon);
    if (typeof candPlaying !== "undefined" && candPlaying >= 0) {
      const b = candPlayBtn(candPlaying); if (b) b.textContent = "▶";
      candPlaying = -1;
    }
    const cp = document.getElementById("cand-player"); if (cp) cp.classList.remove("on", "playing");
  }
  function refreshPlayIcon(svg) {
    const ring = svg.querySelector(".ring"); if (ring) ring.setAttribute("stroke-dashoffset", 2*Math.PI*28);
    const g = svg.querySelector(".glyph"); if (g) g.innerHTML = '<polygon points="-5,-8 13,0 -5,8"/>';
  }
  function togglePreview(url, btn, eqEl) {
    if (!/^https?:\/\//i.test(String(url||""))) return;
    if (playingBtn === btn) { stopAudio(); return; }
    stopAudio(); hap.tap();
    player.src = url;
    player.play().then(() => {
      playingBtn = btn;
      const g = btn.querySelector(".glyph"); if (g) g.innerHTML = '<rect x="-5" y="-7" width="4" height="14" rx="1.5"/><rect x="1" y="-7" width="4" height="14" rx="1.5"/>';
      if (eqEl) eqEl.classList.add("on");
    }).catch(() => hap.err());
    player.ontimeupdate = () => {
      const ring = btn.querySelector(".ring");
      if (!ring || !player.duration) return;
      const c = 2*Math.PI*28;
      ring.setAttribute("stroke-dashoffset", c - c * (player.currentTime/player.duration));
    };
    player.onended = stopAudio;
  }

  /* ── dynamic accent ── */
  let dyn = null;
  function accentColor(fallback){ return dyn || fallback || "var(--primary)"; }
  function extractAccent(img, apply) {
    try {
      const c = document.createElement("canvas"); c.width=c.height=10;
      const x = c.getContext("2d"); x.drawImage(img,0,0,10,10);
      const d = x.getImageData(0,0,10,10).data;
      let best=null, bs=-1;
      for (let i=0;i<d.length;i+=4){const r=d[i],g=d[i+1],b=d[i+2],mx=Math.max(r,g,b),mn=Math.min(r,g,b),lum=(mx+mn)/2,s=(mx-mn)+(lum>40&&lum<215?60:0);if(s>bs){bs=s;best=[r,g,b];}}
      if (best && bs>70) { dyn = "rgb("+best[0]+","+best[1]+","+best[2]+")"; apply(); }
    } catch(e) {}
  }

  /* ── render result ── */
  function renderCard() {
    const r = state.release, f = state.flags;
    const photo = Boolean(f.as_photo), mode = photo || f.large_preview ? "large" : "compact";
    const card = $("post-card");
    card.classList.toggle("large", mode === "large");
    card.classList.toggle("compact", mode === "compact");
    const artSrc = r.artwork_failed ? "" : safeUrl(r.artwork);
    const acc = r.accentColor || "var(--primary)";
    dyn = null;
    const artEmoji = esc(r.emoji || "🎵");
    const artAlt = esc(
      (EN ? "Cover: " : "Обложка: ") + r.artist + " — " + r.title,
    );

    const playSvg =
      '<button class="play-btn" id="play-btn"><svg width="60" height="60" viewBox="0 0 64 64">'+
      '<circle cx="32" cy="32" r="28" fill="rgba(0,0,0,0.7)" stroke="rgba(255,255,255,0.12)" stroke-width="1"/>'+
      '<circle class="ring" cx="32" cy="32" r="28" fill="none" stroke="var(--primary)" stroke-width="2.5" stroke-dasharray="'+(2*Math.PI*28)+'" stroke-dashoffset="'+(2*Math.PI*28)+'" stroke-linecap="round" transform="rotate(-90 32 32)" style="transition:stroke-dashoffset .9s linear"/>'+
      '<g class="glyph" transform="translate(32,32)" fill="#fff"><polygon points="-5,-8 13,0 -5,8"/></g></svg></button>';

    let coverBlock = "";
    if (mode === "large") {
      coverBlock =
        '<div class="cover">'+
        (artSrc
          ? '<img class="cover-art" data-card-art="1" data-emoji="'+artEmoji+'" crossorigin="anonymous" alt="'+artAlt+'" decoding="async" fetchpriority="high" src="'+artSrc+'">'
          : '<div class="cover-art cover-fallback" aria-label="'+artAlt+'">'+artEmoji+"</div>")+
        '<div class="grad"></div>'+
        (r.preview ? '<div class="prev-badge">'+esc(T.preview30)+'</div>' : "")+
        (r.preview ? '<div class="eq" id="card-eq"><i></i><i></i><i></i><i></i><i></i></div>' : "")+
        (r.preview ? playSvg : "")+
        "</div>";
    }

    const genre = r.genre ? '<span class="genre-badge" id="genre-badge">'+esc(r.genre)+"</span>" : "";
    const headBlock =
      '<div class="post-headrow"><div style="min-width:0;flex:1">'+
      '<div class="post-title">'+esc(r.title)+"</div>"+
      '<div class="post-artist">'+esc(r.emoji)+" · "+esc(r.artist)+(r.year?" · "+esc(r.year):"")+"</div></div>"+genre+"</div>";

    const ctaBlock = '<div class="post-cta" id="cta-line">'+esc(r.cta)+'<span class="pencil">✏️</span></div>';
    const tagsBlock = (f.hashtags && r.hashtags)
      ? '<div class="post-tags" id="tags-line">'+r.hashtags.split(/\s+/).filter(Boolean).map((t)=>"<span>"+esc(t)+"</span>").join("")+'<span class="pencil">✏️</span></div>'
      : "";

    const enabled = r.platforms.filter((p)=>p.enabled!==false);
    const readiness = $("result-readiness");
    const readyItems = [
      [Boolean(artSrc), Boolean(artSrc) ? T.readyCover : T.readyNoCover, "disc"],
      [enabled.length > 0, enabled.length+" "+T.readyPlatforms, "check"],
      [Boolean(f.hashtags && r.hashtags), f.hashtags && r.hashtags ? T.readyHashtags : T.readyClean, "sliders"],
    ];
    readiness.innerHTML = readyItems.map(([ok,label,icon]) => '<span class="'+(ok?'ok':'muted')+'">'+ico(icon,"s14")+esc(label)+"</span>").join("");
    const health = assessDraft(state, PREFLIGHT.draft);
    const score = $("result-score");
    $("result-score-value").textContent = health.score;
    score.style.setProperty("--health", String(health.score));
    score.dataset.level = health.score >= 100 ? "ready" : (health.score >= 50 ? "progress" : "attention");
    score.setAttribute(
      "aria-label",
      (EN ? "Post readiness: " : "Готовность поста: ") + health.score + "%",
    );
    let plats = "";
    enabled.forEach((p) => {
      if (!/^https?:\/\//i.test(String(p.url||""))) return;
      const m = PLATFORM_META[p.key] || {color:"#8C8C88",letter:"♪",name:p.label.replace(/^\S+\s/,"")};
      plats += '<a class="plat" href="'+safeUrl(p.url)+'" target="_blank" rel="noopener" style="background:'+m.color+'18;border:1px solid '+m.color+'40;color:'+m.color+'"><span class="pb" style="background:'+m.color+'">'+m.letter+"</span>"+esc(m.name)+"</a>";
    });
    if (/^https?:\/\//i.test(String(r.page_url||""))) plats += '<a class="plat hub" href="'+safeUrl(r.page_url)+'" target="_blank" rel="noopener">+ '+esc(T.allPlatforms)+"</a>";

    let innerTop = "";
    if (mode === "compact") {
      innerTop =
        '<div class="compact-top">'+
        '<div class="compact-cover">'+(artSrc
          ? '<img class="compact-art" data-card-art="1" data-emoji="'+artEmoji+'" crossorigin="anonymous" alt="'+artAlt+'" decoding="async" src="'+artSrc+'">'
          : '<div class="compact-art cover-fallback" aria-label="'+artAlt+'">'+artEmoji+"</div>")+"</div>"+
        '<div style="flex:1;min-width:0">'+headBlock+"</div></div>";
      card.innerHTML = coverBlock + innerTop + '<div class="post-inner" style="padding-top:12px">'+ctaBlock+tagsBlock+'<div class="plats">'+plats+"</div></div>";
    } else {
      card.innerHTML = coverBlock + '<div class="post-inner">'+headBlock+ctaBlock+tagsBlock+'<div class="plats">'+plats+"</div></div>";
    }
    card.style.boxShadow = "0 8px 32px "+acc+"22";
    card.style.borderColor = "var(--border)";

    if (r.preview) {
      const btn = $("play-btn"), eq = $("card-eq");
      if (btn) btn.addEventListener("click", () => togglePreview(r.preview, btn, eq));
    } else if (r.preview_pending && !previewFetching) {
      // Card is already visible — fetch the audio preview in the background and
      // pop the ▶ button in when it arrives.
      previewFetching = true;
      const draftId = state.draft_id;
      api("preview", { draft_id: draftId }).then((res) => {
        previewFetching = false;
        if (!state || state.draft_id !== draftId) return;
        state.release.preview_pending = false;
        if (res && res.ok && res.preview) {
          state.release.preview = res.preview;
          if (!$("v-result").classList.contains("hidden")) renderCard();
        }
      }).catch(() => { previewFetching = false; });
    }
    const ctaLine = $("cta-line"); if (ctaLine) ctaLine.addEventListener("click", () => openFormat());
    const tagsLine = $("tags-line"); if (tagsLine) tagsLine.addEventListener("click", () => openFormat());

    const img = card.querySelector("img");
    card.querySelectorAll("img[data-card-art]").forEach((art) => {
      art.addEventListener("error", () => {
        if (!state || state.release !== r || r.artwork_failed) return;
        r.artwork_failed = true;
        renderCard();
      }, { once: true });
    });
    if (img && !r.accentColor) {
      const apply = () => {
        if (!dyn) return;
        card.style.setProperty("--release-accent",dyn);
        const g = $("genre-badge");
        if (g) { g.style.background = dyn.replace("rgb(", "rgba(").replace(")", ",0.13)"); g.style.color = dyn; g.style.border = "1px solid " + dyn.replace("rgb(", "rgba(").replace(")", ",0.4)"); }
        card.style.boxShadow = "0 8px 32px " + dyn.replace("rgb(", "rgba(").replace(")", ",0.25)");
      };
      if (img.complete) extractAccent(img, apply); else img.addEventListener("load", () => extractAccent(img, apply));
    } else if (r.accentColor) {
      card.style.setProperty("--release-accent",acc);
      const g=$("genre-badge"); if(g){g.style.background=acc+"22";g.style.color=acc;g.style.border="1px solid "+acc+"44";}
    }

    /* dock */
    const main = $("action-main"), sch = $("action-schedule");
    $("dock-default").classList.remove("hidden"); $("dock-done").classList.add("hidden");
    main.classList.remove("done"); main.disabled = false;
    sch.classList.add("hidden");
    if (state.can_publish) { main.innerHTML = ico("send","s18")+esc(T.publish); main.dataset.action="publish"; }
    else { main.innerHTML = ico("send","s18")+esc(T.send); main.dataset.action="send"; }
    showNativeMain(state.can_publish ? T.publish : T.send, openPublish);
    $("status").textContent = "";
  }

  /* ── flows ── */
  async function search(pick) {
    const q = pick || $("query").value.trim();
    if (!q) return;
    // Multiple links pasted at once → build a crate automatically.
    if (!pick && (q.match(/https?:\/\/\S+/g) || []).length >= 2) { return searchBatch(q); }
    lastQuery = q;
    cancelPending(); const seq = loadSeq;
    closeFormat(); show("loading");
    try {
      const res = await api("resolve", { query: q, pick: Boolean(pick) }, { abortable: true });
      if (seq !== loadSeq) return;
      if (res.error === "rate_limited") {
        hap.err(); flash(EN?"Too many searches — wait a moment":"Слишком часто — подожди пару секунд");
        navStack.pop(); const prev = navStack[navStack.length-1] || "home";
        if (prev === "home") loadHome(); show(prev, false); return;
      }
      if (res.error === "network" || res.error === "timeout") {
        hap.err(); flash(errorText(res.error));
        navStack.pop(); const prev = navStack[navStack.length-1] || "home";
        if (prev === "home") loadHome(); show(prev, false); return;
      }
      if (!res.ok) { $("nf-query").textContent = q; show("notfound"); hap.err(); return; }
      if (res.candidates) { renderCandidates(res.candidates); show("candidates"); hap.pick(); return; }
      openDraftResult(res, true);
    } catch(e) { if (seq !== loadSeq) return; $("nf-query").textContent = q; show("notfound"); hap.err(); }
  }
  async function searchBatch(q) {
    lastQuery = q;
    cancelPending(); const seq = loadSeq;
    closeFormat(); show("loading");
    try {
      const res = await api("resolve_batch", { query: q }, { abortable: true, timeout: 30000 });
      if (seq !== loadSeq) return;
      if (res.error === "rate_limited") {
        hap.err(); flash(EN?"Too many searches — wait a moment":"Слишком часто — подожди пару секунд");
        navStack.pop(); const prev = navStack[navStack.length-1] || "home";
        if (prev === "home") loadHome(); show(prev, false); return;
      }
      if (res.error === "network" || res.error === "timeout") {
        hap.err(); flash(errorText(res.error));
        navStack.pop(); const prev = navStack[navStack.length-1] || "home";
        if (prev === "home") loadHome(); show(prev, false); return;
      }
      const found = (res.items || []);
      if (!res.ok || !found.length) { $("nf-query").textContent = q; show("notfound"); hap.err(); return; }
      // merge into the crate, dedupe by artist+title, respect the cap
      const have = new Set(crateItems.map((x)=>((x.data.artist||"")+"|"+(x.data.title||"")).toLowerCase()));
      let added = 0;
      found.forEach((it) => {
        const key = ((it.data.artist||"")+"|"+(it.data.title||"")).toLowerCase();
        if (!have.has(key) && crateItems.length < 10) { have.add(key); crateItems.push(normalizeCrateItem(it)); added++; }
      });
      persistCrate(); refreshCrateBadge(); hap.ok();
      $("query").value = "";
      updateSearchMode();
      openCrate();
      const failed = Math.max(0, Number(res.failed_count) || 0);
      flash(
        failed
          ? (EN
            ? `${added} added · ${failed} not recognized`
            : `Добавлено: ${added} · не распознано: ${failed}`)
          : (EN ? `Added ${added} to the crate` : `Добавлено в подборку: ${added}`),
      );
    } catch(e) { if (seq !== loadSeq) return; $("nf-query").textContent = q; show("notfound"); hap.err(); }
  }
  function openDraftResult(res, applyDefaults) {
    state = res; saveActiveDraft(); show("result"); renderCard(); hap.ok(); maybeCoach();
    if (applyDefaults) loadPrefs((prefs) => {
      if (!prefs) return; const patch = {};
      if (typeof prefs.hashtags==="boolean" && prefs.hashtags!==state.flags.hashtags) patch.hashtags=prefs.hashtags;
      if (typeof prefs.large_preview==="boolean" && prefs.large_preview!==state.flags.large_preview) patch.large_preview=prefs.large_preview;
      if (Array.isArray(prefs.platforms) && prefs.platforms.length) patch.platforms=prefs.platforms;
      if (Object.keys(patch).length) syncDraft(patch, true);
    });
  }
  let candList = [], candPlaying = -1;
  function renderCandidates(cands) {
    candList = cands; candPlaying = -1; $("cand-player").classList.remove("on");
    $("cand-count").textContent = cands.length + " " + plural(cands.length,"release","releases","релиз","релиза","релизов");
    const list = $("cand-list"); list.innerHTML = "";
    cands.forEach((c, i) => {
      const el = document.createElement("div"); el.className = "cand"; el.dataset.idx = i;
      el.innerHTML =
        '<div class="cand-body"><div class="cand-art">'+(safeUrl(c.artwork)?'<img alt="" src="'+safeUrl(c.artwork)+'" style="width:100%;height:100%;object-fit:cover;border-radius:12px">':"🎵")+
        (c.preview?'<button class="cand-play" aria-label="'+(EN?"Play preview":"Воспроизвести отрывок")+'">▶</button>':"")+"</div>"+
        '<div class="cand-meta"><div class="cand-title">'+esc(c.title)+'</div><div class="cand-details"><span class="cand-artist">'+esc(c.artist)+'</span>'+(c.year?'<span class="cand-year">'+esc(c.year)+"</span>":"")+"</div></div>"+
        '<button class="cand-pick" aria-label="'+esc((EN?"Choose ":"Выбрать ")+c.artist+" — "+c.title)+'">'+(EN?"Choose":"Выбрать")+"</button></div>";
      if (c.preview) el.querySelector(".cand-play").addEventListener("click", (e)=>{ e.stopPropagation(); playCandidate(i); });
      el.querySelector(".cand-pick").addEventListener("click", () => { hap.pick(); search(c.url); });
      list.appendChild(el);
      setTimeout(() => el.classList.add("in"), 60 + i*90);
    });
  }
  function candPlayBtn(i) { const el = $("cand-list").querySelector('.cand[data-idx="'+i+'"]'); return el ? el.querySelector(".cand-play") : null; }
  function previewIndices() { return candList.map((c,i)=>c && c.preview ? i : -1).filter((i)=>i>=0); }
  function setPlayGlyph(playing) {
    $("cp-play").textContent = playing ? "⏸" : "▶";
    $("cp-play").setAttribute("aria-label", playing ? (EN?"Pause":"Пауза") : (EN?"Play":"Воспроизвести"));
    const btn = candPlayBtn(candPlaying); if (btn) { btn.textContent = playing ? "⏸" : "▶"; btn.setAttribute("aria-label", playing ? (EN?"Pause preview":"Поставить на паузу") : (EN?"Play preview":"Воспроизвести отрывок")); }
  }
  function playCandidate(i) {
    const c = candList[i]; if (!c || !c.preview) return;
    stopAudio(); hap.tap(); candPlaying = i;
    player.src = c.preview;
    player.play().then(() => {
      $("cp-title").textContent = c.title; $("cp-sub").textContent = c.artist;
      $("cand-player").classList.add("on", "playing"); setPlayGlyph(true);
    }).catch(() => hap.err());
    player.onended = () => { advanceCandidate(1, true); };
    const el = $("cand-list").querySelector('.cand[data-idx="'+i+'"]'); if (el) el.scrollIntoView({ behavior:"smooth", block:"center" });
  }
  function advanceCandidate(dir, auto) {
    const idxs = previewIndices(); if (!idxs.length) { stopAudio(); return; }
    const pos = idxs.indexOf(candPlaying);
    if (pos < 0) { playCandidate(idxs[0]); return; }
    const nextPos = pos + dir;
    if (auto && nextPos >= idxs.length) { stopAudio(); return; }
    playCandidate(idxs[(nextPos + idxs.length) % idxs.length]);
  }
  $("cp-prev").addEventListener("click", () => { hap.pick(); advanceCandidate(-1, false); });
  $("cp-next").addEventListener("click", () => { hap.pick(); advanceCandidate(1, false); });
  $("cp-close").addEventListener("click", () => { hap.tap(); stopAudio(); });
  $("cp-play").addEventListener("click", () => {
    if (candPlaying < 0) return; hap.tap();
    if (player.paused) { player.play(); $("cand-player").classList.add("playing"); setPlayGlyph(true); }
    else { player.pause(); $("cand-player").classList.remove("playing"); setPlayGlyph(false); }
  });
  async function loadDraft(id) {
    cancelPending(); const seq = loadSeq;
    show("loading");
    try {
      const res = await api("draft", { draft_id: id }, { abortable: true });
      if (seq !== loadSeq) return;
      if (res && res.ok) { openDraftResult(res, false); return; }
      if (res?.error === "draft not found") clearActiveDraft();
    } catch(e) { if (seq !== loadSeq) return; }
    loadHome(); show("home");
  }

  /* ── home ── */
  function clearActiveDraft() {
    cloud.remove("activeDraft");
    $("resume-card").classList.add("hidden");
  }
  function saveActiveDraft() {
    const snapshot = createDraftSnapshot(state);
    if (snapshot) cloud.set("activeDraft", JSON.stringify(snapshot));
  }
  function renderActiveDraft(snapshot) {
    const card = $("resume-card");
    if (!snapshot) { card.classList.add("hidden"); return; }
    $("resume-kicker").textContent = EN ? "IN PROGRESS" : "В РАБОТЕ";
    $("resume-title").textContent = snapshot.title || (EN ? "Untitled release" : "Релиз без названия");
    $("resume-sub").textContent = snapshot.artist || (EN ? "Continue editing" : "Продолжить оформление");
    $("resume-action").textContent = T.continueAction;
    const art = $("resume-art");
    art.textContent = snapshot.emoji || "🎵";
    art.style.backgroundImage = safeUrl(snapshot.artwork)
      ? 'url("'+String(snapshot.artwork).replace(/"/g,"%22")+'")'
      : "";
    $("resume-open").onclick = () => { hap.tap(); loadDraft(snapshot.draftId); };
    card.classList.remove("hidden");
  }
  $("resume-dismiss").addEventListener("click", (event) => {
    event.stopPropagation(); hap.tap(); clearActiveDraft();
  });
  function setHomeError(open) {
    $("home-alert").classList.toggle("hidden", !open);
    $("home-alert").setAttribute("aria-hidden", String(!open));
  }
  let homeLoadPromise = null;
  async function loadHome() {
    if (homeLoadPromise) return homeLoadPromise;
    homeLoadPromise = loadHomeData();
    try { return await homeLoadPromise; }
    finally { homeLoadPromise = null; }
  }
  async function loadHomeData() {
    $("quick").classList.remove("hidden");
    if (!isAdmin) { $("q-queue").classList.add("hidden"); $("q-stats").classList.add("hidden"); }
    const localCrate = new Promise((resolve) => loadCrate(resolve));
    cloud.get("activeDraft", (_error, raw) => {
      const snapshot = parseDraftSnapshot(raw);
      if (!snapshot && raw) cloud.remove("activeDraft");
      renderActiveDraft(snapshot);
    });
    try {
      const [res] = await Promise.all([api("dashboard", {}), localCrate]);
      $("home-skel").classList.add("hidden");
      if (!res.ok) { setHomeError(true); $("home-empty").classList.remove("hidden"); return; }
      setHomeError(false);
      isAdmin = Boolean(res.is_admin);
      $("admin-badge").classList.toggle("hidden", !isAdmin);
      $("admin-tools").classList.toggle("hidden", !isAdmin);
      $("quick").classList.remove("hidden");
      $("q-queue").classList.toggle("hidden", !isAdmin);
      $("q-stats").classList.toggle("hidden", !isAdmin);
      $("tab-queue").style.display = isAdmin ? "" : "none";
      const serverCrate = res.crate || {};
      if (!crateItems.length && Array.isArray(serverCrate.items) && serverCrate.items.length) {
        crateItems = adoptCrateItems(serverCrate.items); persistCrate();
      }
      refreshCrateBadge();
      const queue = res.queue || {};
      const queueBadge = $("q-queue-n");
      queueBadge.style.display = queue.count > 0 ? "flex" : "none";
      queueBadge.textContent = queue.count || "";
      $("q-queue-sub").textContent = queue.next_at ? fmtWhen(queue.next_at) : T.quick.queue[1];
      historyItems = res.history || [];
      $("home-history").classList.toggle("hidden", historyItems.length===0);
      $("home-empty").classList.toggle("hidden", historyItems.length>0);
      const list = $("hist-list"); list.innerHTML = "";
      list.previousElementSibling.querySelector(".seclabel").textContent = T.recent;
      historyItems.forEach((it, i) => {
        const b = document.createElement("button"); b.className = "row";
        b.innerHTML = artHtml(it.artwork, it.emoji, "row-art") +
          '<div class="row-meta"><div class="row-title">'+esc(it.title)+'</div><div class="row-sub">'+esc(it.artist)+"</div></div>"+
          (it.posted ? '<span class="row-posted">✓ '+T.posted+"</span>" : '<span class="row-year">'+esc(it.year||"")+"</span>");
        b.addEventListener("click", () => { hap.tap(); search(it.source_url); });
        list.appendChild(b); setTimeout(() => b.classList.add("in"), 40 + i*50);
      });
    } catch(e) { setHomeError(true); $("home-skel").classList.add("hidden"); $("home-empty").classList.remove("hidden"); }
  }
  $("home-retry").addEventListener("click", () => { hap.tap(); setHomeError(false); $("home-skel").classList.remove("hidden"); loadHome(); });
  async function refreshQueueBadge() {
    try {
      const res = await api("queue", {}), items=res.items||[], n=items.length, b=$("q-queue-n");
      b.style.display=n>0?"flex":"none"; b.textContent=n;
      $("q-queue-sub").textContent = n && items[0].publish_at ? fmtWhen(items[0].publish_at) : T.quick.queue[1];
    } catch(e) { $("q-queue-sub").textContent = T.quick.queue[1]; }
  }
  function refreshCrateBadge(data) {
    if (data && Array.isArray(data.items)) crateItems = adoptCrateItems(data.items);
    crateCount = crateItems.length;
    const b=$("q-crate-n"); b.style.display=crateCount>0?"flex":"none"; b.textContent=crateCount;
  }

  /* ── formatting screen ── */
  let editTags = [], pmOrder = [], pmEnabled = {};
  function setFormatSync(mode) {
    const el = $("fmt-sync"); if (!el) return;
    el.className = "sync-state "+mode;
    el.textContent = mode === "saving" ? T.ui.saving : (mode === "error" ? T.ui.saveError : T.ui.saved);
  }
  function openFormat() {
    hap.tap();
    const release = state.release;
    document.querySelectorAll("#format-nav button").forEach((button, index) => button.classList.toggle("active", index === 0));
    $("fmt-preview-title").textContent = release.title;
    $("fmt-preview-sub").textContent = release.artist;
    const previewArt = $("fmt-preview-art");
    previewArt.textContent = release.emoji || "♪";
    previewArt.style.backgroundImage = safeUrl(release.artwork) ? 'url("'+release.artwork.replace(/"/g, "%22")+'")' : "";
    drawToggles();
    $("cta-input").value = state.release.cta; $("cta-count").textContent = state.release.cta.length;
    editTags = (state.release.hashtags||"").split(/\s+/).filter(Boolean); drawTags();
    $("tags-sec").style.display = state.flags.hashtags ? "" : "none";
    pmOrder = state.release.platforms.map((p)=>p.key); pmEnabled = {};
    state.release.platforms.forEach((p)=>{pmEnabled[p.key]=p.enabled!==false;}); drawPm();
    drawPresets(); setFormatSync("saved");
    show("format");
  }

  /* ── style presets (CloudStorage) ── */
  let presets = [];
  function loadPresets(cb) {
    cloud.get("presets", (e,v) => { try { presets = v?JSON.parse(v):[]; } catch(x){ presets=[]; } if(!Array.isArray(presets)) presets=[]; cb&&cb(); });
  }
  function savePresetsStore() { cloud.set("presets", JSON.stringify(presets.slice(0,4))); }
  function drawPresets() {
    const box = $("preset-list");
    const render = () => {
      box.innerHTML = "";
      if (!presets.length) { box.innerHTML = '<div class="eb-s" style="font-size:12px">'+esc(T.presetEmpty)+"</div>"; return; }
      presets.forEach((p, i) => {
        const chip = document.createElement("button"); chip.className = "chip";
        chip.innerHTML = esc(p.name)+' <span class="x">✕</span>';
        chip.addEventListener("click", (ev) => {
          if (ev.target.closest(".x")) { hap.pick(); presets.splice(i,1); savePresetsStore(); render(); return; }
          applyPreset(p);
        });
        box.appendChild(chip);
      });
    };
    if (!presets.length) loadPresets(render); else render();
  }
  function applyPreset(p) {
    hap.ok();
    if (typeof p.hashtags === "boolean") state.flags.hashtags = p.hashtags;
    if (typeof p.as_photo === "boolean") state.flags.as_photo = p.as_photo;
    if (typeof p.large_preview === "boolean") state.flags.large_preview = p.large_preview;
    const patch = { hashtags: state.flags.hashtags, as_photo: state.flags.as_photo, large_preview: state.flags.large_preview };
    if (Array.isArray(p.platforms) && p.platforms.length) patch.platforms = p.platforms;
    if (Array.isArray(p.tags)) patch.tags = p.tags;
    drawToggles();
    syncDraft(patch, true);
    goBack();
  }
  $("preset-save").addEventListener("click", () => {
    hap.tap();
    loadPresets(() => {
      const n = presets.length + 1;
      presets.push({
        name: T.presetName + " " + n,
        hashtags: state.flags.hashtags, as_photo: Boolean(state.flags.as_photo),
        large_preview: state.flags.large_preview,
        platforms: pmSelection(), tags: editTags.slice(),
      });
      savePresetsStore(); drawPresets();
    });
  });
  function closeFormat() { if (!$("v-format").classList.contains("hidden")) {} }
  function drawToggles() {
    const box = $("toggles"); box.innerHTML = "";
    const defs = [["hashtags",T.rHashtags],["quote",T.rQuote,!state.flags.has_prefix],["as_photo",T.rPhoto],["large_preview",T.rBig,Boolean(state.flags.as_photo)]];
    defs.forEach(([k,label,skip]) => {
      if (skip) return;
      const btn = document.createElement("button"); btn.className = "toggle-row";
      btn.innerHTML = "<span>"+esc(label)+'</span><div class="switch'+(state.flags[k]?" on":"")+'"><i></i></div>';
      btn.setAttribute("aria-pressed", String(Boolean(state.flags[k])));
      btn.addEventListener("click", () => {
        hap.pick(); state.flags[k] = !state.flags[k];
        drawToggles(); $("tags-sec").style.display = state.flags.hashtags ? "" : "none";
        const patch={}; patch[k]=state.flags[k]; syncDraft(patch);
      });
      box.appendChild(btn);
    });
  }
  function drawTags() {
    const cloud = $("tag-cloud"); cloud.innerHTML = "";
    editTags = [...new Set(editTags.map((tag) => {
      const clean=String(tag||"").trim().replace(/\s+/g,"").replace(/^#+/,"");
      return clean ? "#"+clean.toLowerCase() : "";
    }).filter(Boolean))].slice(0,8);
    editTags.forEach((t, i) => {
      const p = document.createElement("button"); p.className = "chip";
      p.innerHTML = esc(t)+'<span class="x">✕</span>';
      p.addEventListener("click", () => { hap.pick(); editTags.splice(i,1); drawTags(); syncDraft({tags:editTags.slice()}); });
      cloud.appendChild(p);
    });
    const inp = document.createElement("input"); inp.className = "chip-input"; inp.placeholder = "+ "+T.addTag;
    inp.addEventListener("keydown", (e) => { if (e.key==="Enter" && inp.value.trim()) { e.preventDefault(); hap.pick(); editTags.push(inp.value.trim()); drawTags(); syncDraft({tags:editTags.slice()}); } });
    cloud.appendChild(inp);
    const recommended = (state?.release?.auto_hashtags||"").split(/\s+/).filter((tag)=>tag && !editTags.includes(tag));
    const suggestions = $("tag-suggestions"); suggestions.innerHTML = "";
    if (recommended.length) {
      const label=document.createElement("span"); label.textContent=T.tagRecommended; suggestions.appendChild(label);
      recommended.slice(0,5).forEach((tag)=>{
        const button=document.createElement("button"); button.type="button"; button.textContent="+ "+tag;
        button.addEventListener("click",()=>{hap.pick();editTags.push(tag);drawTags();syncDraft({tags:editTags.slice()});});
        suggestions.appendChild(button);
      });
    }
    const health=$("tag-health"); health.textContent=editTags.length>6?T.tagTooMany:T.tagHealthy;
    health.classList.toggle("warn", editTags.length>6);
  }
  function drawPm() {
    const list = $("pm-list"); list.innerHTML = "";
    pmOrder.forEach((key, i) => {
      const p = state.release.platforms.find((x)=>x.key===key); if (!p) return;
      const m = PLATFORM_META[key] || {color:"#8C8C88",letter:"♪",name:p.label};
      const row = document.createElement("div"); row.className = "pm-row";
      row.innerHTML =
        '<div class="pm-move"><button class="up" aria-label="'+(EN?"Move up":"Поднять выше")+'"'+(i===0?" disabled":"")+">"+ico("up","s14")+'</button><button class="down" aria-label="'+(EN?"Move down":"Опустить ниже")+'"'+(i===pmOrder.length-1?" disabled":"")+">"+ico("down","s14")+"</button></div>"+
        '<div class="pm-badge" style="background:'+m.color+'">'+m.letter+'</div><div class="pm-name">'+esc(m.name)+"</div>"+
        '<button class="pm-check'+(pmEnabled[key]?" on":"")+'" aria-label="'+esc((EN?"Toggle ":"Включить или выключить ")+m.name)+'" aria-pressed="'+String(Boolean(pmEnabled[key]))+'">'+(pmEnabled[key]?ico("check","s14"):"")+"</button>";
      row.querySelector(".up").addEventListener("click", ()=>{ if(i===0)return; hap.pick(); [pmOrder[i-1],pmOrder[i]]=[pmOrder[i],pmOrder[i-1]]; drawPm(); applyPm(); });
      row.querySelector(".down").addEventListener("click", ()=>{ if(i===pmOrder.length-1)return; hap.pick(); [pmOrder[i+1],pmOrder[i]]=[pmOrder[i],pmOrder[i+1]]; drawPm(); applyPm(); });
      row.querySelector(".pm-check").addEventListener("click", ()=>{
        if (pmEnabled[key] && pmSelection().length <= 1) { hap.err(); flash(T.ui.onePlatform); return; }
        hap.pick(); pmEnabled[key]=!pmEnabled[key]; drawPm(); applyPm();
      });
      list.appendChild(row);
    });
  }
  function pmSelection(){ return pmOrder.filter((k)=>pmEnabled[k]); }
  function applyPm(){ const s=pmSelection(); if (s.length) syncDraft({platforms:s}); }
  $("cta-input").addEventListener("input", () => {
    $("cta-count").textContent = $("cta-input").value.length;
    syncDraft({cta:$("cta-input").value.trim() || null});
  });
  $("open-format").addEventListener("click", openFormat);
  $("fmt-apply").addEventListener("click", () => {
    hap.ok();
    const pending = $("tag-cloud").querySelector(".chip-input");
    if (pending && pending.value.trim()) editTags.push(pending.value.trim());
    const patch = { tags: editTags };
    const cta = $("cta-input").value.trim();
    patch.cta = cta && cta !== state.release.cta ? cta : (state.release.cta_custom ? cta : null);
    if (editTags.length && !state.flags.hashtags) patch.hashtags = true;
    savePrefs({ platforms: pmSelection(), hashtags: state.flags.hashtags, large_preview: state.flags.large_preview });
    syncDraft(patch, true);
    goBack();
  });

  function syncDraft(patch, immediate) {
    clearTimeout(syncTimer);
    const run = async () => {
      const seq = ++syncSeq;
      const draftId = state && state.draft_id;
      if (!$("v-format").classList.contains("hidden")) setFormatSync("saving");
      try {
        const res = await api("update", { draft_id: draftId, ...patch });
        // a newer edit already fired — don't let this stale response revert it
        if (seq !== syncSeq) return;
        if (!res || !res.ok) { setFormatSync("error"); return; }
        state = res; saveActiveDraft();
        setFormatSync("saved");
        if (!$("v-result").classList.contains("hidden")) renderCard();
      } catch(e) { if (seq === syncSeq) { setFormatSync("error"); flash(errorText(e.message)); } }
    };
    if (immediate) run(); else syncTimer = setTimeout(run, 350);
  }

  /* ── deliver + undo ── */
  function clearUndo(){ if (undoTimer) { clearInterval(undoTimer); undoTimer=null; } }
  function startUndo(messageId) {
    let left = 5;
    $("dock-default").classList.add("hidden"); $("dock-done").classList.remove("hidden");
    $("done-label").textContent = T.published;
    $("action-undo").dataset.messageId = messageId;
    const upd = () => $("undo-label").textContent = T.undo+" ("+left+")";
    upd(); clearUndo();
    undoTimer = setInterval(() => { left--; if (left<=0) { clearUndo(); renderCard(); return; } upd(); }, 1000);
  }
  $("action-undo").addEventListener("click", async () => {
    clearUndo();
    try { const res = await api("unpublish", { draft_id: state.draft_id, message_id: Number($("action-undo").dataset.messageId||0) }); if (res.ok) { hap.ok(); renderCard(); $("status").textContent = T.undone; } else { hap.err(); renderCard(); } } catch(e) { hap.err(); renderCard(); }
  });
  async function deliver(action, extra) {
    const main = $("action-main"); main.disabled = true; setNativeMainBusy(true);
    try {
      const res = await api(action, { draft_id: state.draft_id, hashtags: state.flags.hashtags, quote: state.flags.quote, large_preview: state.flags.large_preview, as_photo: Boolean(state.flags.as_photo), ...(extra||{}) });
      if (res.ok) {
        hap.ok();
        main.disabled = false;
        if (action==="publish" && res.message_id) { startUndo(res.message_id); showSuccess(action); return; }
        main.classList.add("done"); main.innerHTML = ico("check","s18")+(action==="publish"?T.published:T.sent);
        showSuccess(action);
        setTimeout(() => { renderCard(); }, 2400);
      } else if (res.error==="duplicate") {
        hap.err();
        $("toast-msg").innerHTML = T.dupA+"<b>"+esc(res.posted_date)+"</b>"+T.dupB;
        setToastOpen(true); $("toast-confirm").textContent = T.confirm;
        $("toast-confirm").onclick = () => { setToastOpen(false); deliver("publish", {force:true}); };
      } else { hap.err(); $("status").textContent = errorText(res.error); }
    } catch(e) { hap.err(); $("status").textContent = errorText("network"); }
    finally { setNativeMainBusy(false); if ($("dock-done").classList.contains("hidden")) $("action-main").disabled = false; }
  }
  function closePublish() { setSheetOpen("publish-sheet", "publish-mask", false); }
  function openPublish(mode) {
    publishMode=mode==="crate"?"crate":"draft";
    hap.tap();
    const canPublish=publishMode==="crate"?isAdmin:Boolean(state?.can_publish);
    $("publish-channel").classList.toggle("hidden", !canPublish);
    $("publish-later").classList.toggle("hidden", !canPublish || publishMode==="crate");
    const readiness = publishMode === "crate"
      ? assessCollection(crateItems, collectionMeta, PREFLIGHT.collection)
      : assessDraft(state, PREFLIGHT.draft);
    $("publish-preflight").innerHTML = readiness.checks.map((check) =>
      '<div class="preflight-item '+(check.blocking?"block":check.ok?"ok":"warn")+'">'+
      '<i class="preflight-dot"></i><span>'+esc(check.label)+"</span></div>"
    ).join("");
    $("publish-channel").disabled = !readiness.ready;
    $("publish-self").disabled = !readiness.ready;
    $("publish-later").disabled = !readiness.ready;
    $("publish-copy").disabled = !readiness.ready;
    if(publishMode==="crate"){
      const first=crateItems[0]||{}, title=collectionMeta.title||(EN?"Collection":"Подборка");
      $("publish-summary").innerHTML=artHtml(first.artwork,first.emoji,"publish-art")+
        '<div><b>'+esc(title)+'</b><small>'+esc(crateItems.length+" "+plural(crateItems.length,"track","tracks","трек","трека","треков"))+
        '</small></div><span class="publish-ready">'+ico("check","s14")+(EN?"READY":"ГОТОВО")+"</span>";
    }else{
      const release=state.release, platforms=(release.platforms||[]).filter((p)=>p.enabled!==false).length;
      $("publish-summary").innerHTML =
        artHtml(release.artwork,release.emoji,"publish-art")+
        '<div><b>'+esc(release.artist)+" — "+esc(release.title)+'</b><small>'+
        esc(platforms+" "+T.readyPlatforms+" · "+(state.flags.hashtags?T.readyHashtags:T.readyClean))+
        '</small></div><span class="publish-ready">'+ico("check","s14")+(EN?"READY":"ГОТОВО")+"</span>";
    }
    setSheetOpen("publish-sheet", "publish-mask", true, publishMode==="crate"?$("crate-main"):$("action-main"));
  }
  function showSuccess(action) {
    $("success-stamp").textContent = action === "publish" ? T.ui.publishedStamp : T.ui.sentStamp;
    $("success-title").textContent = action === "publish" ? (EN?"Post is live":"Пост вышел в эфир") : (EN?"Post sent":"Пост отправлен");
    $("success-copy").textContent = action === "publish" ? (EN?"Done. Time to build the next release.":"Готово. Можно собирать следующий релиз.") : (EN?"Check it in your private chat.":"Проверь результат в личном чате.");
    hideNativeMain(); document.querySelector(".wrap").inert = true;
    $("success-screen").classList.add("open"); $("success-screen").setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => $("success-next").focus());
  }
  function hideSuccess() { document.querySelector(".wrap").inert = false; $("success-screen").classList.remove("open"); $("success-screen").setAttribute("aria-hidden", "true"); if (!$("v-result").classList.contains("hidden") && state) renderCard(); }
  $("action-main").addEventListener("click", () => openPublish("draft"));
  $("publish-mask").addEventListener("click", closePublish);
  $("publish-close").addEventListener("click", closePublish);
  $("publish-channel").addEventListener("click", () => { const crate=publishMode==="crate"; closePublish(); if(crate)deliverCrate("crate_publish");else deliver("publish"); });
  $("publish-self").addEventListener("click", () => { const crate=publishMode==="crate"; closePublish(); if(crate)deliverCrate("crate_send");else deliver("send"); });
  $("publish-later").addEventListener("click", () => { closePublish(); openSheet(); });
  $("publish-copy").addEventListener("click", () => { const crate=publishMode==="crate"; closePublish(); if(crate)shareCratePrepared();else $("action-share").click(); });
  $("success-close").addEventListener("click", hideSuccess);
  $("success-next").addEventListener("click", () => { hideSuccess(); loadHome(); show("home"); setTimeout(()=>$("query").focus(),80); });
  $("action-crate").addEventListener("click", async () => {
    hap.tap();
    if (!state || !state.release) { hap.err(); return; }
    const r = state.release;
    const item = { title:r.title, artist:r.artist, kind:r.kind, genre:r.genre,
      page_url:r.page_url, release_year:r.year, thumbnail_url:r.artwork };
    if (!item.page_url) { const p = (r.platforms||[]).find((x)=>/^https?:\/\//i.test(String(x.url||""))); if (p) item.page_url = p.url; }
    try {
      const res = await api("crate_add", { item, items: crateItems.map((x)=>x.data), draft_id: state.draft_id });
      if (res.ok) { hap.ok(); crateItems = adoptCrateItems(res.items||[]); persistCrate(); refreshCrateBadge(); $("status").textContent = T.toCrate.toUpperCase()+" · "+res.count; }
      else { hap.err(); $("status").textContent = res.error==="crate full"?T.crateFull:T.err; }
    } catch(e) { hap.err(); }
  });
  function shareUrl(url) {
    if (!/^https?:\/\//i.test(String(url||""))) return;
    closeShare();
    try { tg.switchInlineQuery(url, ["users","groups","channels"]); } catch(e) { try { tg.switchInlineQuery(url); } catch(x){} }
  }
  function fallbackShare() {
    const enabled = (state?.release?.platforms||[]).find((p)=>p.enabled!==false && /^https?:\/\//i.test(String(p.url||"")));
    shareUrl(state?.release?.page_url || enabled?.url);
  }
  async function sharePreparedPost() {
    if (!state?.draft_id) { fallbackShare(); return; }
    const button = $("share-post");
    if (button.disabled) return;
    button.disabled = true; button.classList.add("busy");
    $("share-post-title").textContent = T.sharePreparing;
    try {
      const res = await api("prepare_share", { draft_id: state.draft_id });
      if (!res?.ok || !res.prepared_message_id || typeof tg.shareMessage !== "function") {
        fallbackShare();
        return;
      }
      closeShare();
      tg.shareMessage(res.prepared_message_id, (sent) => {
        if (sent) { hap.ok(); flash(EN ? "Post sent with buttons" : "Пост отправлен с кнопками"); }
      });
    } catch(e) {
      hap.err();
      flash(T.shareFailed);
      fallbackShare();
    } finally {
      button.disabled = false; button.classList.remove("busy");
      $("share-post-title").textContent = T.sharePost;
    }
  }
  let lastSheetTrigger = null;
  function setSheetOpen(sheetId, maskId, open, trigger) {
    const sheet = $(sheetId), mask = $(maskId);
    if (open) hideNativeMain();
    sheet.classList.toggle("open", open); mask.classList.toggle("open", open);
    sheet.setAttribute("aria-hidden", String(!open)); mask.setAttribute("aria-hidden", String(!open));
    sheet.inert = !open;
    if (open) {
      lastSheetTrigger = trigger || document.activeElement;
      requestAnimationFrame(() => sheet.querySelector(".publish-options button,.quick-grid button,.picker-item,input,button")?.focus());
    } else if (lastSheetTrigger && typeof lastSheetTrigger.focus === "function") {
      lastSheetTrigger.focus(); lastSheetTrigger = null;
    }
    if (!open && !$("v-result").classList.contains("hidden") && state) showNativeMain(state.can_publish ? T.publish : T.send, openPublish);
  }
  function closeShare(){ setSheetOpen("share-sheet", "share-mask", false); }
  $("share-mask").addEventListener("click", closeShare);
  $("share-close").addEventListener("click", closeShare);
  $("share-post").addEventListener("click", () => { hap.tap(); sharePreparedPost(); });
  $("action-share").addEventListener("click", () => {
    hap.tap();
    const en = (state.release.platforms||[]).filter((p)=>p.enabled!==false && /^https?:\/\//i.test(String(p.url||"")));
    const list = $("share-list"); list.innerHTML = "";
    en.forEach((p) => {
      const m = PLATFORM_META[p.key] || {color:"#8C8C88",letter:"♪",name:p.label};
      const b = document.createElement("button"); b.className = "picker-item";
      b.innerHTML = '<span class="picker-badge" style="background:'+m.color+'">'+m.letter+"</span>"+esc(m.name);
      b.addEventListener("click", () => { hap.pick(); shareUrl(p.url); });
      list.appendChild(b);
    });
    if (/^https?:\/\//i.test(String(state.release.page_url||""))) {
      const b = document.createElement("button"); b.className = "picker-item";
      b.innerHTML = '<span class="picker-badge" style="background:var(--primary)">♪</span>'+esc(T.shareAll);
      b.addEventListener("click", () => { hap.pick(); shareUrl(state.release.page_url); });
      list.appendChild(b);
    }
    setSheetOpen("share-sheet", "share-mask", true, $("action-share"));
  });
  $("action-schedule").addEventListener("click", openSheet);

  /* ── illustrated empty state ── */
  function emptyBox(iconName, title, sub, action) {
    return '<div class="empty-box"><div class="eb-ico">'+ico(iconName)+'</div>'+
      '<div><div class="eb-t">'+esc(title)+'</div><div class="eb-s">'+esc(sub)+"</div></div>"+
      (action?'<button class="state-action">'+esc(action)+"</button>":"")+"</div>";
  }
  function loadingRows(count) {
    return Array.from({length:count||3}, () => '<div class="row loading-row" style="opacity:1"><div class="skel row-art"></div><div style="flex:1"><div class="skel loading-line wide"></div><div class="skel loading-line"></div></div></div>').join("");
  }
  function bindStateAction(scope, handler) { scope.querySelector(".state-action")?.addEventListener("click", () => { hap.tap(); handler(); }); }

  function bindSwipe(row, onLeft, onRight) {
    let startX = 0, startY = 0, tracking = false;
    row.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button,.grip,a")) return;
      startX = event.clientX; startY = event.clientY; tracking = true;
    });
    row.addEventListener("pointermove", (event) => {
      if (!tracking) return;
      const dx = event.clientX - startX, dy = event.clientY - startY;
      if (Math.abs(dx) < Math.abs(dy) || Math.abs(dx) < 8) return;
      row.style.transform = "translateX(" + Math.max(-82, Math.min(82, dx)) + "px)";
    });
    const finish = (event) => {
      if (!tracking) return; tracking = false;
      const dx = event.clientX - startX; row.style.transform = "";
      if (dx < -64 && onLeft) { hap.pick(); onLeft(); }
      else if (dx > 64 && onRight) { hap.pick(); onRight(); }
    };
    row.addEventListener("pointerup", finish);
    row.addEventListener("pointercancel", () => { tracking = false; row.style.transform = ""; });
  }

  /* ── schedule / reschedule ── */
  let sheetMode = { type: "schedule" }, schedulePending = false;
  function pickTime(ts) {
    hap.pick();
    if (sheetMode.type === "reschedule") rescheduleJob(sheetMode.jobId, ts);
    else schedule(ts, false);
  }
  async function rescheduleJob(jobId, at) {
    if (schedulePending) return;
    schedulePending = true;
    closeSheet();
    try {
      const res = await api("reschedule", { job_id: jobId, at });
      if (res.ok) { hap.ok(); openQueue(); }
      else { hap.err(); flash(errorText(res.error)); }
    } catch(e) { hap.err(); flash(errorText("network")); }
    finally { schedulePending = false; }
  }
  async function schedule(at, force) {
    if (schedulePending) return;
    schedulePending = true;
    closeSheet();
    try {
      const res = await api("schedule", { draft_id: state.draft_id, at, force: Boolean(force), hashtags: state.flags.hashtags, quote: state.flags.quote, large_preview: state.flags.large_preview, as_photo: Boolean(state.flags.as_photo) });
      if (res.ok) { hap.ok(); $("status").textContent = T.scheduled + fmtWhen(res.publish_at); refreshQueueBadge(); }
      else if (res.error==="duplicate") { hap.err(); $("toast-msg").innerHTML=T.dupA+"<b>"+esc(res.posted_date)+"</b>"+T.dupB; setToastOpen(true); $("toast-confirm").textContent=T.confirm; $("toast-confirm").onclick=()=>{setToastOpen(false);schedule(at,true);}; }
      else { hap.err(); $("status").textContent = errorText(res.error); }
    } catch(e) { hap.err(); $("status").textContent = errorText("network"); }
    finally { schedulePending = false; }
  }
  function fmtWhen(ts){ return new Intl.DateTimeFormat(EN?"en-GB":"ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(ts*1000)); }
  function openSheet(mode) {
    hap.tap();
    sheetMode = mode || { type: "schedule" };
    $("sheet-title").textContent = sheetMode.type === "reschedule" ? T.reschedule : T.sheetTitle;
    const grid = $("quick-grid"); grid.innerHTML = "";
    const now = new Date(), tn = new Date(now); tn.setHours(19,0,0,0);
    const tm = new Date(now); tm.setDate(tm.getDate()+1); tm.setHours(10,0,0,0);
    [[T.in1h,Math.floor(Date.now()/1000)+3600],[T.in3h,Math.floor(Date.now()/1000)+10800],[T.tonight,Math.floor(tn/1000)],[T.tomorrow,Math.floor(tm/1000)]]
      .filter(([,ts])=>ts>Date.now()/1000+60).forEach(([l,ts])=>{const b=document.createElement("button");b.textContent=l;b.addEventListener("click",()=>pickTime(ts));grid.appendChild(b);});
    const d = new Date(Date.now()+3600000); d.setMinutes(0,0,0);
    $("dt-input").value = new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
    setSheetOpen("sheet", "sheet-mask", true, document.activeElement);
  }
  function closeSheet(){ setSheetOpen("sheet", "sheet-mask", false); }
  $("sheet-close").addEventListener("click", closeSheet);
  $("dt-go").addEventListener("click", () => { const v=$("dt-input").value; if(!v)return; const ts=Math.floor(new Date(v).getTime()/1000); if(ts>Date.now()/1000+60){pickTime(ts);}else hap.err(); });
  $("sheet-mask").addEventListener("click", closeSheet);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if ($("coach").classList.contains("open")) closeCoach();
      else if ($("success-screen").classList.contains("open")) hideSuccess();
      else if ($("crate-item-sheet").classList.contains("open")) closeCrateItemEditor();
      else if ($("crate-editor-sheet").classList.contains("open")) closeCrateEditor();
      else if ($("publish-sheet").classList.contains("open")) closePublish();
      else if ($("share-sheet").classList.contains("open")) closeShare();
      else if ($("sheet").classList.contains("open")) closeSheet();
      return;
    }
    if (e.key !== "Tab") return;
    const dialog = $("crate-item-sheet").classList.contains("open") ? $("crate-item-sheet") : ($("crate-editor-sheet").classList.contains("open") ? $("crate-editor-sheet") : ($("publish-sheet").classList.contains("open") ? $("publish-sheet") : ($("share-sheet").classList.contains("open") ? $("share-sheet") : ($("sheet").classList.contains("open") ? $("sheet") : null))));
    if (!dialog) return;
    const focusable = [...dialog.querySelectorAll('button:not([disabled]),input:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter((el)=>el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  /* ── crate (client-authoritative: the list lives in CloudStorage and rides
     along with every request, so a serverless cold start can't lose tracks) ── */
  function normalizeCrateItem(item) {
    return { ...item, meta: item?.meta && typeof item.meta==="object" ? {section:String(item.meta.section||""),note:String(item.meta.note||"")} : {section:"",note:""} };
  }
  function adoptCrateItems(items) {
    const previous=new Map(crateItems.map((item)=>[((item.data?.artist||"")+"|"+(item.data?.title||"")).toLowerCase(),item.meta||{}]));
    return (items||[]).map((item)=>{
      const normalized=normalizeCrateItem(item);
      const key=((normalized.data?.artist||"")+"|"+(normalized.data?.title||"")).toLowerCase();
      normalized.meta=previous.get(key)||normalized.meta;
      return normalized;
    });
  }
  function crateSerialize() {
    return JSON.stringify({
      items:crateItems.map((x)=>({ d:x.data, e:x.emoji, m:x.meta||{} })),
      meta:collectionMeta,
    });
  }
  function crateHydrate(raw) {
    let stored = []; try { stored = JSON.parse(raw)||[]; } catch(e) { stored = []; }
    const arr = Array.isArray(stored) ? stored : (Array.isArray(stored.items)?stored.items:[]);
    if (!Array.isArray(stored) && stored.meta && typeof stored.meta==="object") {
      collectionMeta = {
        title:String(stored.meta.title||""), intro:String(stored.meta.intro||""),
        outro:String(stored.meta.outro||""), tags:Array.isArray(stored.meta.tags)?stored.meta.tags.slice(0,8):[],
      };
    }
    if (!Array.isArray(arr)) return [];
    return arr.filter((o)=>o && o.d).map((o)=>normalizeCrateItem({ artist:o.d.artist, title:o.d.title, emoji:o.e||"📀", artwork:o.d.thumbnail_url, data:o.d, meta:o.m }));
  }
  function persistCrate() { cloud.set("crate1", crateSerialize()); }
  function crateRequestPayload() {
    return {
      items:crateItems.map((x)=>x.data),
      collection:collectionMeta,
      item_meta:crateItems.map((x)=>x.meta||{}),
    };
  }
  function loadCrate(cb) {
    cloud.get("crate1", (err, val) => { if (!err && val) crateItems = crateHydrate(val); cb && cb(); });
  }
  async function openCrate() {
    hap.tap(); show("crate");
    $("crate-dock").classList.add("on");
    loadCrate(async () => {
      let loadFailed = false;
      if (!crateItems.length) {
        try { const res = await api("crate", {}); if (!res.ok) throw new Error(res.error || "network"); if (res.items && res.items.length) { crateItems = adoptCrateItems(res.items); persistCrate(); } } catch(e) { loadFailed = true; }
      }
      drawCrate();
      if (loadFailed && !crateItems.length) {
        const list = $("crate-list"); list.innerHTML = emptyBox("undo", T.ui.loadError, T.network, T.ui.retry); bindStateAction(list, openCrate);
      }
    });
  }
  function drawCrate() {
    const list = $("crate-list"); list.innerHTML = "";
    const crateWord = plural(crateItems.length,"track","tracks","трек","трека","треков");
    $("crate-count").textContent = crateItems.length + " " + crateWord;
    $("crate-cover-count").textContent = crateItems.length + " " + crateWord;
    $("crate-hero-title").textContent=collectionMeta.title||T.ui.crateHero;
    const crateHealth = assessCollection(crateItems, collectionMeta, PREFLIGHT.collection);
    $("crate-health").textContent = crateHealth.score + "%";
    $("crate-health").style.setProperty("--health", String(crateHealth.score));
    $("crate-health").dataset.level = crateHealth.score >= 100 ? "ready" : (crateHealth.score >= 50 ? "progress" : "attention");
    $("crate-health").setAttribute(
      "aria-label",
      (EN ? "Collection readiness: " : "Готовность подборки: ") + crateHealth.score + "%",
    );
    const stack = $("crate-stack").querySelectorAll("i");
    stack.forEach((tile, index) => {
      const item = crateItems[index];
      tile.style.backgroundImage = item && safeUrl(item.artwork) ? 'url("'+String(item.artwork).replace(/"/g,"%22")+'")' : "";
    });
    if (crateItems.length === 0) { list.innerHTML = emptyBox("layers", EN?"Build your next set":"Собери свой следующий сет", EN?"Add releases from any card":"Добавляй релизы из любой карточки"); }
    $("crate-empty").textContent = crateItems.length===1 ? T.needMore : "";
    crateItems.forEach((it, i) => {
      const row = document.createElement("div"); row.className = "row"; row.style.opacity = "1"; row.dataset.i = i;
      const group=it.meta?.section?'<span class="crate-group">'+esc(it.meta.section)+"</span>":"";
      const note=it.meta?.note?'<div class="row-note">'+esc(it.meta.note)+"</div>":"";
      row.innerHTML =
        '<div class="grip">'+ico("grip","s18")+"</div>"+
        '<span class="crate-idx">'+(i+1)+"</span>"+ artHtml(it.artwork, it.emoji, "row-art sm")+
        '<div class="row-meta">'+group+'<div class="row-title">'+esc(it.title)+'</div><div class="row-sub">'+esc(it.artist)+"</div>"+note+"</div>"+
        '<button class="rowbtn edit" aria-label="'+(EN?"Edit track":"Настроить трек")+'">'+ico("sliders","s14")+"</button>"+
        '<button class="rowbtn danger del" aria-label="'+(EN?"Remove track":"Удалить трек")+'">'+ico("trash","s14")+"</button>";
      row.querySelector(".edit").addEventListener("click",()=>openCrateItemEditor(i));
      row.querySelector(".del").addEventListener("click", async () => {
        if (!await confirmAction(T.confirmRemove)) return;
        hap.tap();
        const before = crateItems.slice(), snap = before.map((x)=>x.data);
        crateItems.splice(i, 1); persistCrate(); refreshCrateBadge(); drawCrate();
        try {
          const res = await api("crate_remove", { index:i, items:snap });
          if (!res.ok) throw new Error(res.error || "save_failed");
        } catch (e) {
          crateItems = before; persistCrate(); refreshCrateBadge(); drawCrate();
          hap.err(); flash(errorText(e.message));
        }
      });
      bindDrag(row.querySelector(".grip"), row, i);
      bindSwipe(row, () => row.querySelector(".del").click(), () => { if (i > 0) reorderCrate(i, i - 1); });
      list.appendChild(row);
    });
    const main = $("crate-main"), share = $("crate-share"), clear = $("crate-clear"), enough = crateItems.length>=2;
    main.classList.toggle("hidden", !enough);
    share.classList.toggle("hidden", !enough);
    share.title = T.crateShare; share.setAttribute("aria-label", T.crateShare);
    clear.classList.toggle("hidden", crateItems.length===0);
    clear.textContent = "🗑 "+T.crateClear;
    main.innerHTML = ico("send","s18")+T.continueAction;
  }
  async function reorderCrate(from, to) {
    if (from === to) return;
    hap.pick();
    const before = crateItems.slice(), snap = before.map((x)=>x.data);
    const order = crateItems.map((_,i)=>i);
    const [m] = order.splice(from, 1); order.splice(to, 0, m);
    const [mi] = crateItems.splice(from, 1); crateItems.splice(to, 0, mi);
    persistCrate(); drawCrate();
    try {
      const res = await api("crate_order", { indices: order, items: snap });
      if (!res.ok) throw new Error(res.error || "save_failed");
    } catch (e) {
      crateItems = before; persistCrate(); refreshCrateBadge(); drawCrate();
      hap.err(); flash(errorText(e.message));
    }
  }
  function bindDrag(handle, row, index) {
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const rows = [...$("crate-list").querySelectorAll(".row")];
      const startY = e.clientY;
      row.classList.add("dragging");
      try { handle.setPointerCapture(e.pointerId); } catch(x) {}
      const move = (ev) => { row.style.transform = "translateY(" + (ev.clientY - startY) + "px)"; };
      const up = (ev) => {
        handle.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        row.classList.remove("dragging"); row.style.transform = "";
        let target = 0;
        rows.forEach((r, i) => { if (i === index) return; const rect = r.getBoundingClientRect(); if (ev.clientY > rect.top + rect.height / 2) target++; });
        reorderCrate(index, target);
      };
      handle.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
  }
  async function deliverCrate(action) {
    const main = $("crate-main"); main.disabled = true;
    try { const res = await api(action, crateRequestPayload()); if (res.ok) { hap.ok(); main.classList.add("done"); main.textContent = action==="crate_publish"?T.published:T.sent; if (action==="crate_publish") { crateItems=[]; collectionMeta={title:"",intro:"",outro:"",tags:[]}; persistCrate(); } setTimeout(()=>{refreshCrateBadge();drawCrate();},1600); } else { hap.err(); $("crate-empty").textContent = res.error==="need more tracks"?T.needMore:T.err; } } catch(e) { hap.err(); } finally { main.disabled = false; }
  }
  $("crate-main").addEventListener("click", () => openPublish("crate"));
  async function shareCratePrepared() {
    if (crateItems.length < 2) return;
    const button = $("crate-share");
    button.disabled = true; hap.tap();
    try {
      const res = await api("prepare_crate_share", crateRequestPayload());
      if (!res?.ok || !res.prepared_message_id || typeof tg.shareMessage !== "function") {
        const urls = crateItems.map((x)=>x.data.page_url).filter((url)=>/^https?:\/\//i.test(String(url||"")));
        try { tg.switchInlineQuery(urls.join(" "), ["users","groups","channels"]); }
        catch(e) { try { tg.switchInlineQuery(urls[0]||""); } catch(x) { flash(T.shareFailed); } }
        return;
      }
      tg.shareMessage(res.prepared_message_id, (sent) => {
        if (sent) { hap.ok(); flash(EN ? "Collection sent with buttons" : "Подборка отправлена с кнопками"); }
      });
    } catch(e) { hap.err(); flash(T.shareFailed); }
    finally { button.disabled = false; }
  }
  $("crate-share").addEventListener("click", shareCratePrepared);
  $("crate-clear").addEventListener("click", async () => {
    if (!await confirmAction(T.confirmClear)) return;
    hap.tap();
    const before = crateItems.slice(), beforeMeta={...collectionMeta,tags:[...collectionMeta.tags]};
    crateItems=[]; collectionMeta={title:"",intro:"",outro:"",tags:[]}; persistCrate(); refreshCrateBadge(); drawCrate();
    try {
      const res = await api("crate_clear", {});
      if (!res.ok) throw new Error(res.error || "save_failed");
    } catch (e) {
      crateItems = before; collectionMeta=beforeMeta; persistCrate(); refreshCrateBadge(); drawCrate();
      hap.err(); flash(errorText(e.message));
    }
  });
  function openCrateEditor() {
    hap.medium();
    $("crate-title-input").value=collectionMeta.title;
    $("crate-intro-input").value=collectionMeta.intro;
    $("crate-outro-input").value=collectionMeta.outro;
    $("crate-tags-input").value=collectionMeta.tags.join(" ");
    setSheetOpen("crate-editor-sheet","crate-editor-mask",true,$("crate-edit"));
  }
  function closeCrateEditor(){setSheetOpen("crate-editor-sheet","crate-editor-mask",false);}
  function openCrateItemEditor(index) {
    editingCrateIndex=index; const meta=crateItems[index]?.meta||{};
    $("crate-section-input").value=meta.section||"";
    $("crate-note-input").value=meta.note||"";
    setSheetOpen("crate-item-sheet","crate-item-mask",true,$("crate-list"));
  }
  function closeCrateItemEditor(){setSheetOpen("crate-item-sheet","crate-item-mask",false);editingCrateIndex=-1;}
  $("crate-edit").addEventListener("click",openCrateEditor);
  $("crate-editor-mask").addEventListener("click",closeCrateEditor);
  $("crate-editor-close").addEventListener("click",closeCrateEditor);
  $("crate-editor-save").addEventListener("click",()=>{
    collectionMeta={
      title:$("crate-title-input").value.trim(),
      intro:$("crate-intro-input").value.trim(),
      outro:$("crate-outro-input").value.trim(),
      tags:[...new Set($("crate-tags-input").value.split(/\s+/).map((tag)=>tag.trim()).filter(Boolean).map((tag)=>"#"+tag.replace(/^#+/,"").toLowerCase()))].slice(0,8),
    };
    persistCrate();hap.ok();closeCrateEditor();
    $("crate-hero-title").textContent=collectionMeta.title||T.ui.crateHero;
    flash(EN?"Collection style saved":"Оформление подборки сохранено");
  });
  $("crate-item-mask").addEventListener("click",closeCrateItemEditor);
  $("crate-item-close").addEventListener("click",closeCrateItemEditor);
  $("crate-item-save").addEventListener("click",()=>{
    if(editingCrateIndex<0||!crateItems[editingCrateIndex])return;
    crateItems[editingCrateIndex].meta={section:$("crate-section-input").value.trim(),note:$("crate-note-input").value.trim()};
    persistCrate();hap.ok();closeCrateItemEditor();drawCrate();
  });

  /* ── queue ── */
  async function openQueue() {
    hap.tap(); show("queue");
    const list = $("queue-list"); list.innerHTML = loadingRows(2); $("queue-empty").textContent = "";
    try {
      const res = await api("queue", {}); if (!res.ok) throw new Error(res.error || "network"); const items = res.items||[];
      list.innerHTML = "";
      $("queue-count").textContent = items.length + " " + plural(items.length,"post","posts","пост","поста","постов");
      if (!items.length) { list.innerHTML = emptyBox("clock", EN?"Nothing on air yet":"Пока тишина", EN?"Schedule the next post":"Запланируй следующий пост"); return; }
      items.forEach((it) => {
        const row = document.createElement("div"); row.className = "row"; row.style.opacity = "1";
        row.innerHTML = artHtml(it.artwork, it.emoji, "row-art") +
          '<div class="row-meta"><div class="row-title">'+esc(it.title)+'</div><div class="row-sub">'+esc(it.artist)+'</div><div class="q-time">'+ico("clock","s14")+"<span>"+fmtWhen(it.publish_at)+"</span></div></div>"+
          '<button class="rowbtn edit" aria-label="'+(EN?"Reschedule":"Перенести публикацию")+'">'+ico("clock","s14")+'</button>'+
          '<button class="rowbtn danger del" aria-label="'+(EN?"Remove from queue":"Удалить из очереди")+'">'+ico("trash","s14")+"</button>";
        row.querySelector(".edit").addEventListener("click", ()=>{ hap.tap(); openSheet({ type:"reschedule", jobId: it.id }); });
        row.querySelector(".del").addEventListener("click", async () => {
          if (!await confirmAction(T.confirmRemove)) return;
          hap.tap();
          const button = row.querySelector(".del"); button.disabled = true;
          try {
            const res = await api("unschedule", { job_id:it.id });
            if (!res.ok) throw new Error(res.error || "save_failed");
            row.remove(); refreshQueueBadge();
            if (!list.children.length) list.innerHTML = emptyBox("clock", T.queueEmptyT, T.queueEmptyS);
          } catch (e) {
            button.disabled = false; hap.err(); flash(errorText(e.message));
          }
        });
        bindSwipe(row, () => row.querySelector(".del").click(), () => row.querySelector(".edit").click());
        list.appendChild(row);
      });
    } catch(e) {
      list.innerHTML = emptyBox("undo", T.ui.loadError, errorText(e.message), T.ui.retry);
      bindStateAction(list, openQueue);
    }
  }

  /* ── stats ── */
  async function openStats() {
    hap.tap(); show("stats");
    const scroll = $("v-stats").querySelector(".scroll");
    if (!scroll.dataset.tpl) scroll.dataset.tpl = scroll.innerHTML;
    scroll.innerHTML = '<div class="list stats-loading">'+loadingRows(4)+"</div>";
    try {
      const res = await api("stats", {}); if (!res.ok || !res.stats) throw new Error(res.error || "network"); const s = res.stats;
      const total = ["posts","song","album","podcast","videos","collections"].reduce((a,k)=>a+(Number(s[k])||0),0);
      if (total === 0) { scroll.innerHTML = emptyBox("bar", T.statsEmptyT, T.statsEmptyS); return; }
      if (!$("kpi-grid")) {
        scroll.innerHTML = scroll.dataset.tpl;
        $("top-users-lbl").textContent = T.topUsers; $("top-chats-lbl").textContent = T.topChats;
      }
      const kpi = $("kpi-grid"); kpi.innerHTML = "";
      [["posts",s.posts],["song",s.song],["album",s.album],["podcast",s.podcast]].forEach(([k,v]) => {
        const c = document.createElement("div"); c.className = "kpi";
        c.innerHTML = '<div class="k-l">'+T.stat[k]+'</div><div class="k-v">'+(Number(v)||0)+"</div>";
        kpi.appendChild(c);
      });
      const bd = [["song",s.song,"#C97A1E"],["album",s.album,"#E5C38A"],["podcast",s.podcast,"#A0522D"],["videos",s.videos,"#8C8C88"],["collections",s.collections,"#D4A574"]];
      const bmax = Math.max(1, ...bd.map(([,v])=>Number(v)||0));
      $("stat-breakdown").innerHTML = bd.map(([k,v,c]) => {
        const val = Number(v)||0;
        return '<div class="bar-row"><span class="bar-label">'+T.stat[k]+'</span><div class="bar-track"><div class="bar-fill" style="background:'+c+'"></div></div><span class="bar-num">'+val+"</span></div>";
      }).join("");
      requestAnimationFrame(() => { let i=0; $("stat-breakdown").querySelectorAll(".bar-fill").forEach((el)=>{el.style.width=((Number(bd[i][1])||0)/bmax*100)+"%";i++;}); });
      drawTopBars("stat-users", s.top_users||[]);
      drawTopBars("stat-chats", s.top_chats||[]);
    } catch(e) {
      scroll.innerHTML = emptyBox("undo", T.ui.loadError, errorText(e.message), T.ui.retry);
      bindStateAction(scroll, openStats);
    }
  }
  function drawTopBars(id, entries) {
    const box = $(id);
    if (!entries.length) { box.innerHTML = '<div class="status-note" style="text-align:left;margin:0">—</div>'; return; }
    const max = Math.max(1, ...entries.map((e)=>e.count));
    box.innerHTML = entries.map((e) => '<div class="bar-row"><span class="bar-label">'+esc(e.label)+'</span><div class="bar-track"><div class="bar-fill"></div></div><span class="bar-num">'+(Number(e.count)||0)+"</span></div>").join("");
    requestAnimationFrame(() => { let i=0; box.querySelectorAll(".bar-fill").forEach((el)=>{el.style.width=(entries[i].count/max*100)+"%";i++;}); });
  }

  /* ── search box events ── */
  function updateSearchMode() {
    const mode = analyzeQuery($("query").value, 10);
    const button = $("search-go");
    button.disabled = mode.empty;
    button.setAttribute("aria-disabled", String(mode.empty));
    $("searchbar").classList.toggle("batch", mode.mode === "batch");
    if (mode.mode === "batch") {
      const suffix = mode.overflow > 0
        ? (EN ? ` · first 10` : ` · первые 10`)
        : "";
      $("batch-label").textContent = EN
        ? `${mode.linkCount} links → build crate${suffix}`
        : `${mode.linkCount} ссылок → собрать подборку${suffix}`;
      $("batch-label").classList.add("batch-ready");
      button.setAttribute("aria-label", EN ? "Build a crate" : "Собрать подборку");
      button.innerHTML = ico("layers", "s18");
    } else {
      $("batch-label").textContent = T.batch;
      $("batch-label").classList.remove("batch-ready");
      button.setAttribute("aria-label", EN ? "Find release" : "Найти релиз");
      button.innerHTML = ico("cr", "s18");
    }
  }
  $("query").addEventListener("keydown", (e) => { if (e.key==="Enter" && !$("search-go").disabled) search(); });
  $("search-go").addEventListener("click", () => search());
  $("query").addEventListener("input", () => { $("clear").style.display = $("query").value?"block":"none"; updateSearchMode(); renderTypeahead(); });
  $("query").addEventListener("focus", () => $("searchbar").classList.add("focus"));
  $("query").addEventListener("blur", () => { $("searchbar").classList.remove("focus"); setTimeout(()=>$("typeahead").classList.remove("open"),180); });
  $("clear").addEventListener("click", () => { $("query").value=""; $("clear").style.display="none"; updateSearchMode(); $("query").focus(); });
  $("paste-btn").addEventListener("click", () => {
    hap.tap();
    tryClipboard((text) => {
      const value = String(text || "").trim();
      if (!value) { flash(EN?"Clipboard is empty":"В буфере ничего нет"); return; }
      $("query").value = value;
      $("clear").style.display = "block";
      updateSearchMode();
      renderTypeahead();
      $("query").focus();
      hap.ok();
    });
  });
  $("nf-retry").addEventListener("click", () => {
    hap.tap(); loadHome(); show("home");
    $("query").value = lastQuery || ""; $("clear").style.display = lastQuery ? "block" : "none";
    updateSearchMode();
    setTimeout(() => { $("query").focus(); $("query").select(); }, 80);
  });
  $("toast-cancel").addEventListener("click", () => setToastOpen(false));

  function renderTypeahead() {
    const box = $("typeahead"), q = $("query").value.trim().toLowerCase();
    if (q.length<2) { box.classList.remove("open"); return; }
    const hits = historyItems.filter((it)=>(it.artist+" "+it.title).toLowerCase().includes(q)).slice(0,4);
    if (!hits.length) { box.classList.remove("open"); return; }
    box.innerHTML = "";
    hits.forEach((it) => {
      const b = document.createElement("button");
      b.innerHTML = artHtml(it.artwork, it.emoji, "ta-art")+"<span>"+esc(it.artist)+" – <b>"+esc(it.title)+'</b></span><span class="ta-clock">'+ico("clock","s14")+"</span>";
      b.addEventListener("click", () => { hap.pick(); box.classList.remove("open"); $("query").value=it.artist+" – "+it.title; search(it.source_url); });
      box.appendChild(b);
    });
    box.classList.add("open");
  }

  /* ── clipboard ── */
  function tryClipboard(cb) {
    try { tg.readTextFromClipboard(cb); return; } catch(e) {}
    if (navigator.clipboard && navigator.clipboard.readText) navigator.clipboard.readText().then(cb).catch(()=>{});
  }
  (function initClip() {
    let dismissed = false;
    tryClipboard((text) => {
      const m = String(text||"").match(/https?:\/\/\S+/); if (!m || dismissed) return;
      let host = ""; try { host = new URL(m[0]).hostname.replace(/^www\./,""); } catch(e) { return; }
      $("clip-text").innerHTML = esc(T.clipQ)+" <b>"+esc(host)+"</b>";
      $("clip-banner").classList.add("open");
      $("clip-banner").onclick = (ev) => { if (ev.target.closest(".cb-x")) { dismissed=true; $("clip-banner").classList.remove("open"); return; } hap.ok(); $("clip-banner").classList.remove("open"); $("query").value=m[0]; updateSearchMode(); search(); };
    });
  })();

  /* ── coach ── */
  let coachShown = false;
  function closeCoach() {
    $("coach-mask").classList.remove("open"); $("coach-mask").setAttribute("aria-hidden", "true");
    $("coach").classList.remove("open"); $("coach").setAttribute("aria-hidden", "true"); $("coach").inert = true;
  }
  function maybeCoach() {
    if (coachShown) return; coachShown = true;
    const KEY = "coach4", start = () => setTimeout(startCoach, 800);
    try { cloud.get(KEY,(e,v)=>{ if(e||v)return; start(); cloud.set(KEY,"1"); }); }
    catch(e) { try{ if(!localStorage.getItem(KEY)){start();localStorage.setItem(KEY,"1");} }catch(x){} }
  }
  function startCoach() {
    let step = 0; const steps = T.coach;
    const render = () => {
      $("coach-step").textContent = T.step+" "+(step+1)+" / "+steps.length;
      $("coach-emoji").textContent = steps[step][0]; $("coach-title").textContent = steps[step][1]; $("coach-text").textContent = steps[step][2];
      $("coach-dots").innerHTML = steps.map((_,i)=>"<i"+(i===step?' class="on"':"")+"></i>").join("");
      $("coach-next").textContent = step===steps.length-1?T.gotIt:T.next;
    };
    $("coach-skip").textContent = T.skip;
    $("coach-mask").classList.add("open"); $("coach-mask").setAttribute("aria-hidden", "false");
    $("coach").classList.add("open"); $("coach").setAttribute("aria-hidden", "false"); $("coach").inert = false; render();
    requestAnimationFrame(() => $("coach-next").focus());
    $("coach-next").onclick = () => { hap.tap(); step++; if (step>=steps.length) { closeCoach(); return; } render(); };
    $("coach-skip").onclick = closeCoach;
    $("coach-mask").onclick = closeCoach;
  }

  /* ── native ── */
  (function initNative() {
    if (tg.isVersionAtLeast && tg.isVersionAtLeast("8.0")) {
      const fs = $("fs-btn"); fs.classList.remove("hidden");
      fs.addEventListener("click", () => { hap.tap(); try { tg.isFullscreen ? tg.exitFullscreen() : tg.requestFullscreen(); } catch(e) {} });
    }
  })();

  /* ── boot ── */
  const params = new URLSearchParams(window.location.search);
  updateSearchMode();
  const draftParam = params.get("draft") || tg.initDataUnsafe?.start_param;
  const viewParam = params.get("view");
  const localDemo = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) && params.get("demo");
  if (localDemo === "result") {
    openDraftResult({
      ok:true, draft_id:"demo", can_publish:true,
      flags:{hashtags:true,quote:false,large_preview:true,as_photo:false,has_prefix:false},
      release:{artist:"Electric Wizard",title:"Funeralopolis",kind:"song",emoji:"⚡",year:"2000",genre:"Doom Metal",artwork:location.origin+"/assets/studio-demo.svg",page_url:"https://song.link/demo",preview:null,preview_pending:false,cta:"громкость выше — мир тише",hashtags:"#stonerhand #doom #electricwizard",platforms:[{key:"spotify",label:"Spotify",url:"https://open.spotify.com",enabled:true},{key:"appleMusic",label:"Apple Music",url:"https://music.apple.com",enabled:true},{key:"youtubeMusic",label:"YouTube",url:"https://music.youtube.com",enabled:true}]}
    }, false);
  } else if (localDemo === "crate") {
    isAdmin = true;
    crateItems = ["Funeralopolis","Dragonaut","Green Machine"].map((title,index)=>({title,artist:["Electric Wizard","Sleep","Kyuss"][index],emoji:"⚡",artwork:location.origin+"/assets/studio-demo.svg",data:{title,artist:["Electric Wizard","Sleep","Kyuss"][index],thumbnail_url:location.origin+"/assets/studio-demo.svg",page_url:"https://song.link/demo",kind:"song"}}));
    show("crate"); $("crate-dock").classList.add("on"); drawCrate();
  } else if (draftParam) { loadDraft(draftParam); loadHome(); }
  else if (["crate","queue","stats"].includes(viewParam)) {
    show("home");
    loadHome().then(() => {
      if (viewParam === "crate") openCrate();
      else if (viewParam === "queue") openQueue();
      else openStats();
    });
  } else { show("home"); loadHome(); }
})();
