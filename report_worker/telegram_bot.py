from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from docx import Document
from pypdf import PdfReader
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .preflight import (
    format_preset_catalog,
    report_setup_questions,
    setup_answer_brief,
)
from .providers import GeminiProvider
from .quality_gate import format_quality_notes, review_output_quality, review_render_log
from .report_pipeline import generate_report, should_use_staged_generation
from .renderer import render_report
from .request_router import needs_web_research
from .settings_vault import SettingsVault
from .user_profiles import UserProfileStore, infer_asset_role
from .worker import build_user_prompt


LOGGER = logging.getLogger("report-telegram")
MODE_KEY = "report_mode"
GUIDED_OUTPUT_KEY = "guided_output"
RAW_REPORT_KEY = "raw_report"
ASSETS_KEY = "brand_assets"
PENDING_RENDER_KEY = "pending_render"
LAST_REPORT_KEY = "last_report"
VAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "settings.json"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def looks_like_new_report(text: str) -> bool:
    markers = ("عنوان التقرير", "الملخص", "المطلوب:", "مؤشرات الأداء", "التحديات:")
    return len(text) > 500 or sum(marker in text for marker in markers) >= 2


def review_message(output: dict[str, Any]) -> str:
    audit = output.get("audit") or {}
    notes = [
        str(item.get("note") or item.get("message") or "").strip()
        for item in audit.get("contradictions", [])
    ]
    missing = [str(item).strip() for item in audit.get("missing_information", [])]
    lines = [line for line in notes if line]
    lines.extend(f"معلومة تحتاج استكمالًا: {item}" for item in missing if item)
    if not lines:
        return ""
    return "ملاحظات مراجعة خارج التقرير، يرجى اعتمادها قبل النشر النهائي:\n\n" + "\n".join(
        f"• {line}" for line in lines
    )


def visual_identity_questions(report_text: str) -> list[dict[str, Any]]:
    lowered = report_text.lower()
    definitions = [
        (
            ("شعار", "ختم"),
            {
                "id": "identity_assets",
                "question": "هل تريد إضافة شعار أو ختم للجهة؟",
                "reason": "تحديد عناصر الهوية الرسمية قبل تصميم الغلاف والصفحات.",
                "required": True,
                "options": [
                    {"id": "logo_stamp", "label": "شعار وختم", "recommended": False},
                    {"id": "logo_only", "label": "شعار فقط", "recommended": True},
                    {"id": "stamp_only", "label": "ختم فقط", "recommended": False},
                    {"id": "no_assets", "label": "بدون شعار أو ختم", "recommended": False},
                ],
            },
        ),
        (
            ("خلفية", "صورة غلاف", "صورة للغلاف"),
            {
                "id": "cover_background",
                "question": "كيف تريد الغلاف وخلفيات الصفحات؟",
                "reason": "اختيار مستوى استخدام الصور والخلفيات دون التأثير في القراءة.",
                "required": True,
                "options": [
                    {"id": "geometric", "label": "غلاف هندسي وخلفية بيضاء", "recommended": True},
                    {"id": "cover_image", "label": "صورة غلاف مخصصة", "recommended": False},
                    {"id": "soft_background", "label": "خلفية خفيفة للصفحات", "recommended": False},
                    {"id": "custom_background", "label": "خلفية مخصصة سأصفها", "recommended": False},
                ],
            },
        ),
        (
            ("نمط", "طابع", "تصميم"),
            {
                "id": "visual_style",
                "question": "ما النمط البصري المناسب للتقرير؟",
                "reason": "تحديد أسلوب العناوين والغلاف والمخططات.",
                "required": True,
                "options": [
                    {"id": "executive-modern", "label": "تنفيذي حديث", "recommended": True},
                    {"id": "official-formal", "label": "رسمي مؤسسي", "recommended": False},
                    {"id": "academic-clean", "label": "أكاديمي هادئ", "recommended": False},
                    {"id": "heritage-elegant", "label": "تراثي أنيق", "recommended": False},
                ],
            },
        ),
        (
            ("ألوان", "الوان", "لون", "هوية لونية"),
            {
                "id": "color_palette",
                "question": "ما لوحة الألوان المطلوبة؟",
                "reason": "توحيد ألوان الغلاف والعناوين والمخططات.",
                "required": True,
                "options": [
                    {"id": "navy_teal", "label": "كحلي وفيروزي", "recommended": True},
                    {"id": "logo_colors", "label": "ألوان الشعار", "recommended": False},
                    {"id": "neutral", "label": "ألوان محايدة", "recommended": False},
                    {"id": "custom", "label": "ألوان مخصصة سأحددها", "recommended": False},
                ],
            },
        ),
    ]
    return [
        question
        for keywords, question in definitions
        if not any(keyword in lowered for keyword in keywords)
    ]


def format_questions(questions: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"{index}. {question.get('question')}\n"
        + "\n".join(
            f"- {option.get('label')}"
            + (" (موصى به)" if option.get("recommended") else "")
            for option in question.get("options", [])
        )
        for index, question in enumerate(questions, 1)
    )


def format_assets(assets: list[dict[str, str]]) -> str:
    if not assets:
        return "لا توجد صور محفوظة."
    role_labels = {
        "logo": "شعار",
        "stamp": "ختم",
        "cover": "غلاف",
        "background": "خلفية",
    }
    lines = []
    for asset in assets:
        name = asset.get("file_name") or Path(asset.get("path", "")).name
        role = role_labels.get(asset.get("role", "logo"), "صورة")
        lines.append(f"• {role}: {name}")
    return "الصور المحفوظة حاليًا:\n" + "\n".join(lines)


def approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("اعتماد PDF", callback_data="render:approve"),
                InlineKeyboardButton("إلغاء", callback_data="render:cancel"),
            ]
        ]
    )


def looks_like_edit_request(text: str) -> bool:
    markers = (
        "عدل",
        "عدّل",
        "غير",
        "غيّر",
        "اختصر",
        "احذف",
        "أضف",
        "اضف",
        "بدل",
        "بدّل",
        "اللون",
        "النمط",
        "الشعار",
        "المخطط",
    )
    return len(text) < 600 and any(marker in text for marker in markers)


def format_report_preview(
    output: dict[str, Any],
    provider: dict[str, Any],
    assets: list[dict[str, str]],
) -> str:
    report = output.get("report") or {}
    decisions = output.get("decisions") or {}
    audit = output.get("audit") or {}
    chart_count = len(output.get("chart_intents", []))
    missing_count = len(audit.get("missing_information", []))
    contradiction_count = len(audit.get("contradictions", []))
    title = report.get("title") or "بدون عنوان"
    subtitle = report.get("subtitle") or "لا يوجد عنوان فرعي"
    theme = decisions.get("theme_id") or "غير محدد"
    lines = [
        "معاينة قبل إنشاء PDF:",
        f"• العنوان: {title}",
        f"• العنوان الفرعي: {subtitle}",
        f"• النمط: {theme}",
        f"• الأقسام: {len(report.get('sections', []))}",
        f"• المؤشرات: {len(report.get('kpis', []))}",
        f"• المخططات: {chart_count}",
        f"• الصور/الهوية: {len(assets)}",
        f"• ملاحظات تحتاج انتباهًا: {missing_count + contradiction_count}",
        f"• النموذج: {provider.get('model', 'غير محدد')}",
        "",
        "يمكنك الآن اعتماد PDF، أو إرسال تعديل مثل: غيّر النمط إلى رسمي، اختصر التقرير، احذف المخطط الثاني.",
    ]
    return "\n".join(lines)


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("المسار السريع", callback_data="mode:fast"),
                InlineKeyboardButton("المسار الموجه", callback_data="mode:guided"),
            ]
        ]
    )


class TelegramReportBot:
    def __init__(self, vault: SettingsVault | None = None):
        self.vault = vault or SettingsVault(VAULT_PATH)
        self.profiles = UserProfileStore(VAULT_PATH.parent)
        self.application: Application | None = None

    def _user_id(self, update: Update) -> int | None:
        return update.effective_user.id if update.effective_user else None

    def _profile_assets(self, update: Update) -> list[dict[str, str]]:
        return list(self.profiles.get(self._user_id(update)).get("assets", []))

    def _profile_instruction(self, update: Update) -> str:
        profile = self.profiles.get(self._user_id(update))
        parts = []
        if profile.get("preferred_theme_id"):
            parts.append(f"- النمط المحفوظ للمستخدم: {profile['preferred_theme_id']}.")
        if profile.get("assets"):
            parts.append("- توجد صور هوية محفوظة للمستخدم؛ استخدمها عند طلب شعار أو غلاف أو ختم.")
        if profile.get("brand_note"):
            parts.append(f"- ملاحظة الهوية: {profile['brand_note']}.")
        if not parts:
            return ""
        return "هوية المستخدم المحفوظة، تستخدم ما لم يطلب المستخدم خلافها:\n" + "\n".join(parts)

    def _remember_output_identity(self, update: Update, output: dict[str, Any]) -> None:
        decisions = output.get("decisions") or {}
        theme_id = decisions.get("theme_id")
        if theme_id:
            self.profiles.save(self._user_id(update), {"preferred_theme_id": theme_id})

    def _active_assets(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> list[dict[str, str]]:
        profile_assets = self._profile_assets(update)
        session_assets = context.user_data.get(ASSETS_KEY, [])
        combined = profile_assets + session_assets
        seen: set[str] = set()
        unique = []
        for asset in combined:
            path = str(asset.get("path", ""))
            if path and path not in seen:
                seen.add(path)
                unique.append(asset)
        return unique

    def _runtime_settings(self) -> Settings:
        values = self.vault.load()
        return Settings(
            provider=values["provider"],
            fallback_provider=values["fallback_provider"],
            ollama_base_url=values["ollama_base_url"],
            ollama_model=values["ollama_model"],
            gemini_api_key=values["gemini_api_key"],
            gemini_model=values["gemini_model"],
        )

    def _allowed(self, update: Update) -> bool:
        allowed = self.vault.allowed_users()
        return not allowed or bool(update.effective_user and update.effective_user.id in allowed)

    async def _guard(self, update: Update) -> bool:
        if self._allowed(update):
            return True
        await update.effective_message.reply_text("هذا البوت خاص وغير متاح لهذا الحساب.")
        return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.message.reply_text(
            "مرحبًا بك في بوت التقارير العربية.\n\n"
            "اختر المسار، ثم أرسل نص التقرير الخام. في المسار السريع سأختار النمط "
            "وأعالج النقص تلقائيًا، وفي الموجه سأسألك عن النمط والهوية والصور قبل البناء.\n\n"
            "يمكنك إرسال شعار أو صورة غلاف كصورة أو ملف قبل التقرير، واكتب /presets "
            "لعرض القوالب الجاهزة. استخدم /identity لعرض الهوية المحفوظة.",
            reply_markup=keyboard(),
        )

    async def mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        query = update.callback_query
        await query.answer()
        selected = query.data.split(":", 1)[1]
        context.user_data[MODE_KEY] = selected
        context.user_data.pop(GUIDED_OUTPUT_KEY, None)
        context.user_data.pop(RAW_REPORT_KEY, None)
        context.user_data.pop(PENDING_RENDER_KEY, None)
        text = "السريع" if selected == "fast" else "الموجه"
        await query.message.reply_text(f"تم اختيار المسار {text}. أرسل نص التقرير الآن.")

    async def render_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        query = update.callback_query
        await query.answer()
        action = query.data.split(":", 1)[1]
        pending = context.user_data.get(PENDING_RENDER_KEY)
        if not pending:
            await query.message.reply_text("لا توجد معاينة تنتظر الاعتماد.")
            return
        if action == "cancel":
            context.user_data.pop(PENDING_RENDER_KEY, None)
            await query.message.reply_text("تم إلغاء المعاينة. أرسل تقريرًا جديدًا أو تعديلًا لاحقًا.")
            return
        waiting = await query.message.reply_text("جارٍ إنشاء PDF المعتمد...")
        try:
            await self._send_pdf(
                query.message,
                context,
                pending["output"],
                pending.get("assets", []),
            )
            context.user_data[LAST_REPORT_KEY] = pending
            context.user_data.pop(PENDING_RENDER_KEY, None)
            await waiting.delete()
        except Exception as error:
            LOGGER.exception("Approved PDF rendering failed")
            await waiting.edit_text(f"تعذر إنشاء PDF المعتمد: {str(error)[:350]}")

    async def presets(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.message.reply_text(format_preset_catalog())

    async def identity(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        profile = self.profiles.get(self._user_id(update))
        theme = profile.get("preferred_theme_id") or "لم يحفظ نمط دائم بعد"
        await update.message.reply_text(
            f"الهوية المحفوظة:\n• النمط المفضل: {theme}\n"
            + format_assets(profile.get("assets", []))
        )

    async def clear_identity(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        self.profiles.clear(self._user_id(update))
        context.user_data.pop(ASSETS_KEY, None)
        await update.message.reply_text("تم مسح الهوية البصرية المحفوظة لهذا المستخدم.")

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        public = self.vault.public()
        await update.message.reply_text(
            "حالة الإعدادات:\n"
            f"المزوّد الافتراضي: {public['provider']}\n"
            f"Gemini API: {public['gemini_api_key']}\n"
            f"Telegram Token: {public['telegram_bot_token']}"
        )

    async def text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        mode = context.user_data.get(MODE_KEY)
        if not mode:
            await update.message.reply_text("اختر المسار أولًا.", reply_markup=keyboard())
            return
        pending = context.user_data.get(PENDING_RENDER_KEY)
        if pending:
            await self._revise_pending(update, context, update.message.text.strip(), pending)
            return
        if context.user_data.get(LAST_REPORT_KEY) and looks_like_edit_request(update.message.text.strip()):
            await self._revise_pending(
                update,
                context,
                update.message.text.strip(),
                context.user_data[LAST_REPORT_KEY],
                after_delivery=True,
            )
            return
        await self._process_report(update, context, update.message.text.strip())

    async def document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        document = update.message.document
        suffix = Path(document.file_name or "").suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            await self._store_document_asset(update, context, suffix)
            return
        if not context.user_data.get(MODE_KEY):
            await update.message.reply_text("اختر المسار أولًا.", reply_markup=keyboard())
            return
        if suffix not in {".txt", ".pdf", ".docx"}:
            await update.message.reply_text("الأنواع المدعومة حاليًا: TXT وPDF وDOCX، أو صور PNG/JPG/WEBP للهوية البصرية.")
            return
        if document.file_size and document.file_size > 20 * 1024 * 1024:
            await update.message.reply_text("حجم الملف أكبر من 20 ميجابايت.")
            return
        waiting = await update.message.reply_text("جارٍ قراءة الملف...")
        try:
            telegram_file = await document.get_file()
            folder = Path(tempfile.mkdtemp(prefix="telegram-upload-"))
            path = folder / f"input{suffix}"
            await telegram_file.download_to_drive(path)
            report_text = await asyncio.to_thread(self._extract_text, path)
            await waiting.delete()
            await self._process_report(update, context, report_text)
        except Exception as error:
            LOGGER.exception("Telegram document extraction failed")
            await waiting.edit_text(f"تعذر قراءة الملف: {str(error)[:350]}")

    async def photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        photo = update.message.photo[-1]
        folder = Path(tempfile.mkdtemp(prefix="telegram-asset-"))
        path = folder / "uploaded-photo.jpg"
        telegram_file = await photo.get_file()
        await telegram_file.download_to_drive(path)
        role = infer_asset_role(update.message.caption or "")
        asset = self.profiles.add_asset(
            self._user_id(update), path, "uploaded-photo.jpg", role
        )
        assets = context.user_data.setdefault(ASSETS_KEY, [])
        assets.append(asset)
        del assets[:-4]
        await update.message.reply_text(
            "حفظت الصورة كعنصر هوية بصرية للتقرير القادم.\n" + format_assets(assets)
        )

    async def _store_document_asset(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        suffix: str,
    ) -> None:
        document = update.message.document
        if document.file_size and document.file_size > 20 * 1024 * 1024:
            await update.message.reply_text("حجم الصورة أكبر من 20 ميجابايت.")
            return
        folder = Path(tempfile.mkdtemp(prefix="telegram-asset-"))
        safe_name = f"asset-{len(context.user_data.get(ASSETS_KEY, [])) + 1}{suffix}"
        path = folder / safe_name
        telegram_file = await document.get_file()
        await telegram_file.download_to_drive(path)
        role = infer_asset_role(" ".join([document.file_name or "", update.message.caption or ""]))
        asset = self.profiles.add_asset(
            self._user_id(update), path, document.file_name or safe_name, role
        )
        assets = context.user_data.setdefault(ASSETS_KEY, [])
        assets.append(asset)
        del assets[:-4]
        await update.message.reply_text(
            "حفظت الصورة كعنصر هوية بصرية للتقرير القادم.\n" + format_assets(assets)
        )

    async def _revise_pending(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        edit_text: str,
        pending: dict[str, Any],
        after_delivery: bool = False,
    ) -> None:
        waiting = await update.message.reply_text("سأطبق التعديل وأعرض معاينة جديدة...")
        base_report = pending.get("report_text") or context.user_data.get(RAW_REPORT_KEY, "")
        previous = json.dumps(pending.get("output", {}), ensure_ascii=False, separators=(",", ":"))
        instructions = "\n".join(
            [
                "طلب تعديل على آخر تقرير قبل إعادة التصدير:",
                edit_text,
                "حافظ على الحقائق والأرقام ولا تضف معلومة غير موجودة.",
                "الناتج السابق للمرجعية فقط:",
                previous[:12000],
            ]
        )
        try:
            output, provider = await asyncio.to_thread(
                self._generate,
                context.user_data.get(MODE_KEY, "guided"),
                base_report,
                "\n\n".join(part for part in (self._profile_instruction(update), instructions) if part),
            )
            quality = review_output_quality(output)
            if not quality["ok"]:
                await waiting.edit_text(
                    "أوقفت النسخة المعدلة لأن فحص الجودة وجد عبارات لا تصلح للنشر:\n"
                    + "\n".join(f"• {item}" for item in quality["blockers"])
                )
                return
            new_pending = {
                "output": output,
                "provider": provider,
                "report_text": base_report,
                "assets": self._active_assets(update, context),
            }
            context.user_data[PENDING_RENDER_KEY] = new_pending
            if after_delivery:
                context.user_data[LAST_REPORT_KEY] = new_pending
            await waiting.edit_text(
                format_report_preview(output, provider, new_pending["assets"]),
                reply_markup=approval_keyboard(),
            )
        except Exception as error:
            LOGGER.exception("Pending report revision failed")
            await waiting.edit_text(f"تعذر تطبيق التعديل: {str(error)[:350]}")

    async def _process_report(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        report_text: str,
    ) -> None:
        mode = context.user_data.get(MODE_KEY, "fast")
        pending = context.user_data.get(GUIDED_OUTPUT_KEY)
        setup_instructions = ""
        if pending and looks_like_new_report(report_text):
            context.user_data.pop(GUIDED_OUTPUT_KEY, None)
            context.user_data.pop(RAW_REPORT_KEY, None)
            pending = None
        pending_stage = pending.get("stage") if isinstance(pending, dict) else ""
        if pending_stage == "report_setup":
            raw_report = context.user_data.get(RAW_REPORT_KEY, "")
            setup_instructions = setup_answer_brief(raw_report, report_text)
            report_text = raw_report
            context.user_data.pop(GUIDED_OUTPUT_KEY, None)
            context.user_data.pop(RAW_REPORT_KEY, None)
        elif pending:
            report_text = (
                context.user_data.get(RAW_REPORT_KEY, "")
                + "\n\nإجابات المستخدم على أسئلة المسار الموجه:\n"
                + report_text
            )
            context.user_data.pop(GUIDED_OUTPUT_KEY, None)
            context.user_data.pop(RAW_REPORT_KEY, None)
        elif mode == "guided":
            questions = report_setup_questions(report_text)
            context.user_data[GUIDED_OUTPUT_KEY] = {
                "stage": "report_setup",
                "questions": questions,
            }
            context.user_data[RAW_REPORT_KEY] = report_text
            assets_note = ""
            all_assets = self._active_assets(update, context)
            if all_assets:
                assets_note = "\n\n" + format_assets(all_assets)
            await update.message.reply_text(
                "مساعد إعداد التقرير قبل التوليد:\n"
                "أرسل اختياراتك في رسالة واحدة، ويمكنك إضافة أي لون أو وصف مخصص. "
                "بعدها سأراجع المحتوى وأبني التقرير.\n\n"
                + format_questions(questions)
                + assets_note
            )
            return
        waiting_text = (
            "التقرير طويل؛ بدأت معالجته على مراحل مع تثبيت الهوية والمصطلحات. "
            "قد يستغرق ذلك عدة دقائق..."
            if should_use_staged_generation(report_text)
            else "بدأ تحليل التقرير، قد يستغرق عدة دقائق..."
        )
        waiting = await update.message.reply_text(waiting_text)
        try:
            output, provider = await asyncio.to_thread(
                self._generate,
                mode,
                report_text,
                "\n\n".join(
                    part
                    for part in (self._profile_instruction(update), setup_instructions)
                    if part
                ),
            )
            if output.get("status") == "needs_user_input":
                context.user_data[GUIDED_OUTPUT_KEY] = output
                context.user_data[RAW_REPORT_KEY] = report_text
                context.user_data[MODE_KEY] = "fast"
                await waiting.edit_text(
                    "وجدت نقاطًا تحتاج قرارك. أرسل إجاباتك في رسالة واحدة، ثم سأبني التقرير:\n\n"
                    + format_questions(output.get("questions", []))
                )
                return
            self._remember_output_identity(update, output)
            quality = review_output_quality(output)
            if not quality["ok"]:
                await waiting.edit_text(
                    "أوقفت إرسال التقرير لأن فحص الجودة وجد عبارات لا تصلح للنشر:\n"
                    + "\n".join(f"• {item}" for item in quality["blockers"])
                    + "\n\nأرسل توجيهًا مختصرًا لإصلاحها أو أعد إرسال التقرير."
                )
                return
            assets = self._active_assets(update, context)
            pending_payload = {
                "output": output,
                "provider": provider,
                "report_text": report_text,
                "assets": assets,
            }
            if mode == "guided":
                context.user_data[PENDING_RENDER_KEY] = pending_payload
                await waiting.edit_text(
                    format_report_preview(output, provider, assets),
                    reply_markup=approval_keyboard(),
                )
                return
            await self._send_pdf(update.message, context, output, assets)
            context.user_data[LAST_REPORT_KEY] = pending_payload
            context.user_data.pop(GUIDED_OUTPUT_KEY, None)
            context.user_data.pop(RAW_REPORT_KEY, None)
            await waiting.delete()
        except Exception as error:
            LOGGER.exception("Telegram report processing failed")
            await waiting.edit_text(f"تعذر إنشاء التقرير: {str(error)[:350]}")

    async def _send_pdf(
        self,
        message: Any,
        context: ContextTypes.DEFAULT_TYPE,
        output: dict[str, Any],
        assets: list[dict[str, str]],
    ) -> Path:
        pdf_path = await asyncio.to_thread(
            render_report,
            output,
            Path(tempfile.mkdtemp(prefix="telegram-report-")),
            assets,
        )
        caption = "تم إعداد التقرير بنجاح."
        with pdf_path.open("rb") as pdf:
            await message.reply_document(pdf, filename="report.pdf", caption=caption)
        review = review_message(output)
        if review:
            await message.reply_text(review[:3900])
        quality_notes = format_quality_notes(review_render_log(pdf_path))
        if quality_notes:
            await message.reply_text(quality_notes[:3900])
        return pdf_path

    def _extract_text(self, path: Path) -> str:
        if path.suffix == ".txt":
            text = path.read_text(encoding="utf-8", errors="replace")
        elif path.suffix == ".pdf":
            text = "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        else:
            text = "\n\n".join(
                paragraph.text for paragraph in Document(path).paragraphs if paragraph.text
            )
        if len(text.strip()) < 20:
            raise ValueError("لم أتمكن من استخراج نص كافٍ من الملف")
        return text

    def _generate(
        self,
        mode: str,
        report_text: str,
        instructions: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        settings = self._runtime_settings()
        system = settings.system_prompt_path.read_text(encoding="utf-8")
        schema = json.loads(settings.response_schema_path.read_text(encoding="utf-8"))
        research_sources = []
        if (
            self.vault.load().get("enable_web_research")
            and settings.gemini_api_key
            and needs_web_research(report_text)
        ):
            research = GeminiProvider(settings).research(report_text)
            research_sources = research.sources
            source_lines = "\n".join(
                f"- {source['title']}: {source['url']}" for source in research.sources
            )
            report_text += (
                "\n\nمادة بحث موثقة جلبتها طبقة البحث عبر الإنترنت:\n"
                + research.content
                + "\n\nالمصادر:\n"
                + source_lines
            )
        result, fallback_used, primary_error = generate_report(
            settings=settings,
            primary=settings.provider,
            fallback=settings.fallback_provider,
            system=system,
            user=build_user_prompt(mode, report_text, instructions),
            schema=schema,
            mode=mode,
            report_text=report_text,
            instructions=instructions,
        )
        return result.parsed, {
            "name": result.provider,
            "model": result.model,
            "fallback_used": fallback_used,
            "primary_error": primary_error,
            "web_sources": research_sources,
        }

    def build(self) -> Application:
        token = self.vault.load()["telegram_bot_token"]
        if not token:
            raise ValueError("احفظ مفتاح تيليغرام في لوحة التحكم أولًا")
        application = Application.builder().token(token).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("status", self.status))
        application.add_handler(CommandHandler("presets", self.presets))
        application.add_handler(CommandHandler("identity", self.identity))
        application.add_handler(CommandHandler("clearidentity", self.clear_identity))
        application.add_handler(CallbackQueryHandler(self.render_action, pattern=r"^render:"))
        application.add_handler(CallbackQueryHandler(self.mode, pattern=r"^mode:"))
        application.add_handler(MessageHandler(filters.PHOTO, self.photo))
        application.add_handler(MessageHandler(filters.Document.ALL, self.document))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text))
        self.application = application
        return application

    def run_polling(self) -> None:
        application = self.build()
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            stop_signals=None,
        )

    async def run_async(self, ready: asyncio.Event | None = None) -> None:
        application = self.build()
        try:
            await application.initialize()
            await set_commands(application)
            if application.updater is None:
                raise RuntimeError("Telegram updater is unavailable")
            await application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
            await application.start()
            if ready:
                ready.set()
            await asyncio.Event().wait()
        finally:
            if ready and not ready.is_set():
                ready.set()
            if application.updater and application.updater.running:
                await application.updater.stop()
            if application.running:
                await application.stop()
            await application.shutdown()


async def set_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "بدء تقرير جديد"),
            BotCommand("status", "عرض حالة الربط"),
            BotCommand("presets", "عرض قوالب التقارير"),
            BotCommand("identity", "عرض الهوية المحفوظة"),
            BotCommand("clearidentity", "مسح الهوية المحفوظة"),
        ]
    )
