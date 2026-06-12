const STORAGE_KEYS = {
  settings: "reportar.settings",
  identity: "reportar.identity",
  reports: "reportar.reports"
};

const demoText = `تقرير موجز عن جودة تجربة العملاء في الربع الثاني.

ارتفع معدل الرضا من 78% إلى 86%، وانخفض زمن الاستجابة من 9 ساعات إلى 4 ساعات.
زادت الشكاوى المتعلقة بالتأخير في التسليم بنسبة 12%، بينما تحسنت تقييمات الدعم الفني إلى 4.6 من 5.

المطلوب: صياغة تقرير تنفيذي عربي، إضافة توصيات عملية، وبناء مخططات مقارنة واتجاه زمني.`;

const $ = (selector) => document.querySelector(selector);

function readJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "") || fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function normalizeApiUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function currentSettings() {
  return readJson(STORAGE_KEYS.settings, { apiBaseUrl: "", devToken: "" });
}

function currentReports() {
  return readJson(STORAGE_KEYS.reports, []);
}

function setApiStatus(status, message) {
  const dot = $("#apiStatusDot");
  const text = $("#apiStatusText");
  dot.classList.remove("ok", "bad");
  if (status) dot.classList.add(status);
  text.textContent = message;
}

function setNotice(message, isError = false) {
  const box = $("#submitResult");
  box.textContent = message;
  box.classList.toggle("error", isError);
}

function fileNames(input) {
  return Array.from(input.files || []).map((file) => file.name);
}

function renderReports() {
  const list = $("#reportsList");
  const reports = currentReports();
  if (!reports.length) {
    list.innerHTML = `<div class="notice">لا توجد طلبات بعد. ابدأ من تبويب تقرير جديد.</div>`;
    return;
  }

  list.innerHTML = reports
    .map(
      (report) => `
        <article class="report-item">
          <strong>${escapeHtml(report.title)}</strong>
          <span class="report-meta">
            ${escapeHtml(report.createdAt)} · ${escapeHtml(report.modeLabel)} · ${escapeHtml(report.status)}
          </span>
          <span>${escapeHtml(report.summary)}</span>
          ${report.remoteId ? `<span class="report-meta">رقم المهمة على الخادم: ${escapeHtml(report.remoteId)}</span>` : ""}
        </article>
      `
    )
    .join("");
}

function renderIdentity() {
  const identity = readJson(STORAGE_KEYS.identity, null);
  const preview = $("#identityPreview");
  if (!identity) {
    preview.innerHTML = `<span>لم تحفظ هوية بعد.</span>`;
    return;
  }

  preview.innerHTML = `
    <span class="identity-chip">الجهة: ${escapeHtml(identity.organization || "غير محدد")}</span>
    <span class="identity-chip"><span class="color-dot" style="background:${escapeAttribute(identity.primaryColor)}"></span> اللون الأساسي</span>
    <span class="identity-chip">الشعار: ${escapeHtml(identity.logo || "لم يرفع")}</span>
    <span class="identity-chip">الختم: ${escapeHtml(identity.stamp || "لم يرفع")}</span>
  `;
}

function loadSettingsForm() {
  const settings = currentSettings();
  $("#settingsForm").apiBaseUrl.value = settings.apiBaseUrl || "";
  $("#settingsForm").devToken.value = settings.devToken || "";
  setApiStatus("", settings.apiBaseUrl ? "API محفوظ، لم يختبر بعد" : "واجهة جاهزة للنشر");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

async function submitToApi(payload) {
  const settings = currentSettings();
  const apiBaseUrl = normalizeApiUrl(settings.apiBaseUrl);
  if (!apiBaseUrl) return null;

  const response = await fetch(`${apiBaseUrl}/api/admin/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(settings.devToken ? { Authorization: `Bearer ${settings.devToken}` } : {})
    },
    body: JSON.stringify({
      report_text: payload.reportText,
      instructions: payload.instructions,
      mode: payload.mode,
      ai_provider: payload.provider || null,
      fallback_allowed: true
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text.slice(0, 220) || `HTTP ${response.status}`);
  }

  return response.json();
}

$("#fillDemo").addEventListener("click", () => {
  const form = $("#reportForm");
  form.title.value = "تقرير جودة تجربة العملاء";
  form.reportText.value = demoText;
  form.mode.value = "fast";
  form.provider.value = "local";
  form.theme.value = "data-dashboard";
  form.charts.value = "required";
  setNotice("تم وضع مثال جاهز. يمكنك تعديله ثم إرسال الطلب.");
});

$("#reportForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    title: form.title.value.trim(),
    reportText: form.reportText.value.trim(),
    mode: form.mode.value,
    provider: form.provider.value,
    theme: form.theme.value,
    charts: form.charts.value,
    files: fileNames(form.files),
    instructions: `النمط البصري: ${form.theme.value}. سياسة المخططات: ${form.charts.value}.`
  };

  if (!payload.title || !payload.reportText) {
    setNotice("أدخل عنوان التقرير ونصه أولًا.", true);
    return;
  }

  setNotice("جارٍ إنشاء الطلب...");
  let remoteId = "";
  let status = "محفوظ محليًا";

  try {
    const remote = await submitToApi(payload);
    if (remote?.job?.id) {
      remoteId = remote.job.id;
      status = "مرسل للخادم";
    }
  } catch (error) {
    status = "محفوظ محليًا، تعذر إرسال الخادم";
    setNotice(`تم حفظ الطلب محليًا، لكن الاتصال بالخادم تعذر: ${error.message}`, true);
  }

  const reports = currentReports();
  reports.unshift({
    id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
    remoteId,
    title: payload.title,
    modeLabel: payload.mode === "guided" ? "مسار موجه" : "مسار سريع",
    status,
    summary: payload.reportText.replace(/\s+/g, " ").slice(0, 130),
    createdAt: new Intl.DateTimeFormat("ar-SA", { dateStyle: "medium", timeStyle: "short" }).format(new Date()),
    files: payload.files
  });
  writeJson(STORAGE_KEYS.reports, reports.slice(0, 20));
  renderReports();

  if (status === "مرسل للخادم") {
    setNotice(`تم إرسال الطلب للخادم بنجاح. رقم المهمة: ${remoteId}`);
  } else if (!normalizeApiUrl(currentSettings().apiBaseUrl)) {
    setNotice("تم حفظ الطلب محليًا. اربط عنوان API في الإعدادات لإرسال الطلبات للخادم.");
  }
});

$("#identityForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const identity = {
    organization: form.organization.value.trim(),
    primaryColor: form.primaryColor.value,
    logo: fileNames(form.logo)[0] || "",
    stamp: fileNames(form.stamp)[0] || ""
  };
  writeJson(STORAGE_KEYS.identity, identity);
  renderIdentity();
});

$("#settingsForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  writeJson(STORAGE_KEYS.settings, {
    apiBaseUrl: normalizeApiUrl(form.apiBaseUrl.value),
    devToken: form.devToken.value.trim()
  });
  loadSettingsForm();
  setApiStatus("", "تم حفظ إعداد API");
});

$("#testApi").addEventListener("click", async () => {
  const settings = currentSettings();
  const apiBaseUrl = normalizeApiUrl(settings.apiBaseUrl);
  if (!apiBaseUrl) {
    setApiStatus("bad", "أدخل عنوان API أولًا");
    return;
  }

  setApiStatus("", "جارٍ اختبار الاتصال...");
  try {
    const response = await fetch(`${apiBaseUrl}/health`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setApiStatus("ok", "الاتصال بالخادم ناجح");
  } catch (error) {
    setApiStatus("bad", `تعذر الاتصال: ${error.message}`);
  }
});

let deferredInstallPrompt = null;
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  $("#installButton").hidden = false;
});

$("#installButton").addEventListener("click", async () => {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  $("#installButton").hidden = true;
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      setApiStatus("bad", "تعذر تفعيل وضع التطبيق دون اتصال");
    });
  });
}

loadSettingsForm();
renderIdentity();
renderReports();
