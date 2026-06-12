const STORAGE_KEYS = {
  identity: "reportar.identity",
  reports: "reportar.reports"
};

const PUBLIC_API_BASE_URL = "";
const POLLABLE_STATUSES = new Set(["مرسل للمعالجة", "قيد الانتظار", "قيد المعالجة", "جاري بناء PDF"]);

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

function currentReports() {
  return readJson(STORAGE_KEYS.reports, []);
}

function apiBaseUrl() {
  return normalizeApiUrl(window.REPORTAR_API_BASE_URL || PUBLIC_API_BASE_URL);
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
          ${report.remoteId ? `<span class="report-meta">رقم الطلب: ${escapeHtml(report.remoteId)}</span>` : ""}
          ${report.downloadUrl ? `<a class="download-link" href="${escapeAttribute(report.downloadUrl)}" target="_blank" rel="noopener">تحميل PDF</a>` : ""}
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

function updateSubmitMode() {
  const connected = Boolean(apiBaseUrl());
  const button = $("#submitButton");
  const banner = $("#modeBanner");

  button.textContent = connected ? "إرسال الطلب" : "حفظ الطلب كمعاينة";
  banner.classList.toggle("connected", connected);
  banner.textContent = connected
    ? "تم تفعيل استقبال الطلبات. سيتم إرسال الطلب للمعالجة."
    : "وضع المعاينة مفعل الآن. سيحفظ الطلب داخل المتصفح إلى أن يتم تفعيل استقبال الطلبات.";
}

function loadAppState() {
  setApiStatus("", "واجهة العملاء");
  updateSubmitMode();
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
  const baseUrl = apiBaseUrl();
  if (!baseUrl) return null;

  const response = await fetch(`${baseUrl}/api/app/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      report_text: payload.reportText,
      instructions: payload.instructions,
      mode: payload.mode,
      visual_theme: payload.theme,
      chart_policy: payload.charts
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text.slice(0, 220) || `HTTP ${response.status}`);
  }

  return response.json();
}

async function fetchJobStatus(jobId) {
  const baseUrl = apiBaseUrl();
  if (!baseUrl || !jobId) return null;
  const response = await fetch(`${baseUrl}/api/app/jobs/${encodeURIComponent(jobId)}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function publicDownloadUrl(downloadUrl) {
  if (!downloadUrl) return "";
  if (/^https?:\/\//i.test(downloadUrl)) return downloadUrl;
  return `${apiBaseUrl()}${downloadUrl}`;
}

function updateReportFromJob(job) {
  const reports = currentReports();
  const index = reports.findIndex((report) => report.remoteId === job.id);
  if (index < 0) return;

  const statusMap = {
    queued: "قيد الانتظار",
    claimed: "قيد المعالجة",
    analyzing: "قيد المعالجة",
    rendering: "جاري بناء PDF",
    completed: "جاهز للتحميل",
    waiting_for_user: "يحتاج مراجعة",
    failed: "تعذر المعالجة"
  };
  reports[index] = {
    ...reports[index],
    status: statusMap[job.status] || job.status,
    downloadUrl: publicDownloadUrl(job.download_url),
    fileName: job.file_name || reports[index].fileName || ""
  };
  writeJson(STORAGE_KEYS.reports, reports);
  renderReports();
}

async function pollJob(jobId, remainingAttempts = 120) {
  if (!apiBaseUrl() || !jobId || remainingAttempts <= 0) return;
  try {
    const response = await fetchJobStatus(jobId);
    const job = response?.job;
    if (!job) return;
    updateReportFromJob(job);
    if (!["completed", "failed", "waiting_for_user"].includes(job.status)) {
      window.setTimeout(() => pollJob(jobId, remainingAttempts - 1), 5000);
    }
  } catch {
    window.setTimeout(() => pollJob(jobId, remainingAttempts - 1), 8000);
  }
}

function resumePolling() {
  if (!apiBaseUrl()) return;
  for (const report of currentReports()) {
    if (report.remoteId && !report.downloadUrl && POLLABLE_STATUSES.has(report.status)) {
      pollJob(report.remoteId, 60);
    }
  }
}

$("#fillDemo").addEventListener("click", () => {
  fillDemoReport();
});

$("#heroDemo").addEventListener("click", () => {
  fillDemoReport();
  document.querySelector("#new").scrollIntoView({ behavior: "smooth", block: "start" });
});

function fillDemoReport() {
  const form = $("#reportForm");
  form.title.value = "تقرير جودة تجربة العملاء";
  form.reportText.value = demoText;
  form.mode.value = "fast";
  form.theme.value = "data-dashboard";
  form.charts.value = "required";
  setNotice("تم وضع مثال جاهز. يمكنك تعديله ثم إرسال الطلب.");
}

$("#reportForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    title: form.title.value.trim(),
    reportText: form.reportText.value.trim(),
    mode: form.mode.value,
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
  const apiConnected = Boolean(apiBaseUrl());
  let remoteId = "";
  let status = "محفوظ محليًا";

  try {
    const remote = await submitToApi(payload);
    if (remote?.job?.id) {
      remoteId = remote.job.id;
      status = "مرسل للمعالجة";
      window.setTimeout(() => pollJob(remoteId), 1000);
    }
  } catch (error) {
    status = "محفوظ محليًا، تعذر الإرسال";
    setNotice(`تم حفظ الطلب محليًا، لكن إرساله تعذر: ${error.message}`, true);
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

  if (status === "مرسل للمعالجة") {
    setNotice(`تم إرسال الطلب بنجاح. رقم الطلب: ${remoteId}`);
  } else if (!apiConnected) {
    setNotice("تم حفظ الطلب كمعاينة داخل المتصفح فقط. بعد تفعيل استقبال الطلبات سيصل للمعالجة وإنتاج PDF.");
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

loadAppState();
renderIdentity();
renderReports();
resumePolling();
