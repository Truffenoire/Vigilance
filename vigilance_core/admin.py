"""
Configuration de l'interface d'administration Django pour Vigilance.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages
from .models import Company, DocumentRequirement, UploadRequest, SubmittedDocument


class UploadRequestInline(admin.TabularInline):
    model = UploadRequest
    extra = 0
    fields = ('created_at', 'expires_at', 'deposit_link_display', 'is_revoked', 'revocation_reason')
    readonly_fields = ('created_at', 'deposit_link_display')
    can_delete = False

    def deposit_link_display(self, obj):
        if not obj or not obj.pk:
            return "-"
        url = obj.get_deposit_url()
        status_color = "#16a34a" if obj.is_valid() else "#dc2626"
        status_text = "Actif" if obj.is_valid() else ("Révoqué" if obj.is_revoked else "Expiré")
        return format_html(
            '<a href="{}" target="_blank" style="font-weight:600; text-decoration:underline;">Ouvrir le lien de dépôt</a> '
            '<span style="margin-left:8px; padding:2px 8px; border-radius:4px; color:white; background:{}; font-size:11px;">{}</span>',
            url, status_color, status_text
        )
    deposit_link_display.short_description = "Lien public partenaire"


class SubmittedDocumentInline(admin.TabularInline):
    model = SubmittedDocument
    extra = 0
    fields = ('submitted_at', 'requirement', 'original_filename', 'status_badge', 'has_usable_text', 'storage_backend')
    readonly_fields = ('submitted_at', 'requirement', 'original_filename', 'status_badge', 'has_usable_text', 'storage_backend')
    can_delete = False

    def status_badge(self, obj):
        return _render_status_badge(obj.status)
    status_badge.short_description = "Statut"


def _render_status_badge(status):
    colors = {
        SubmittedDocument.Status.RECU: ("#e0f2fe", "#0369a1"),
        SubmittedDocument.Status.FORMAT_VALIDE: ("#fef9c3", "#854d0e"),
        SubmittedDocument.Status.TEXTE_EXTRAIT: ("#ede9fe", "#6d28d9"),
        SubmittedDocument.Status.ARCHIVE_DRIVE: ("#dcfce7", "#15803d"),
        SubmittedDocument.Status.A_EXAMINER: ("#ffedd5", "#c2410c"),
        SubmittedDocument.Status.ERREUR: ("#fee2e2", "#b91c1c"),
    }
    bg, fg = colors.get(status, ("#f3f4f6", "#374151"))
    labels = dict(SubmittedDocument.Status.choices)
    label = labels.get(status, status)
    return format_html(
        '<span style="background-color:{}; color:{}; padding:3px 10px; border-radius:12px; font-weight:600; font-size:12px; display:inline-block;">{}</span>',
        bg, fg, label
    )


@admin.register(DocumentRequirement)
class DocumentRequirementAdmin(admin.ModelAdmin):
    list_display = ('order', 'name', 'code', 'is_mandatory')
    list_display_links = ('name',)
    list_editable = ('order', 'is_mandatory')
    search_fields = ('name', 'code')


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'siren', 'contact_name', 'contact_email', 'active_link_display', 'documents_summary', 'created_at')
    search_fields = ('name', 'siren', 'contact_name', 'contact_email')
    filter_horizontal = ('required_documents',)
    inlines = [UploadRequestInline, SubmittedDocumentInline]
    actions = ['generate_standard_link', 'generate_permanent_link']

    def active_link_display(self, obj):
        req = obj.get_active_upload_request()
        if req:
            url = req.get_deposit_url()
            return format_html(
                '<a href="{}" target="_blank" style="color:#0284c7; font-weight:600;">Lien actif</a>',
                url
            )
        return format_html('<span style="color:#9ca3af;">Aucun lien actif</span>')
    active_link_display.short_description = "Lien de dépôt"

    def documents_summary(self, obj):
        count = obj.documents.count()
        archived = obj.documents.filter(status=SubmittedDocument.Status.ARCHIVE_DRIVE).count()
        errors = obj.documents.filter(status=SubmittedDocument.Status.ERREUR).count()
        if errors > 0:
            return format_html('<span style="color:#dc2626; font-weight:bold;">{} doc(s) ({} erreurs)</span>', count, errors)
        return format_html('<span>{} doc(s) ({} archivés)</span>', count, archived)
    documents_summary.short_description = "Documents"

    @admin.action(description="Générer un lien de dépôt (30 jours) pour les entreprises sélectionnées")
    def generate_standard_link(self, request, queryset):
        created_count = 0
        for company in queryset:
            UploadRequest.create_for_company(company, days_valid=30)
            created_count += 1
        self.message_user(request, f"{created_count} nouveau(x) lien(s) de dépôt généré(s) avec succès.", messages.SUCCESS)

    @admin.action(description="Générer un lien de dépôt permanent pour les entreprises sélectionnées")
    def generate_permanent_link(self, request, queryset):
        created_count = 0
        for company in queryset:
            UploadRequest.create_for_company(company, days_valid=None)
            created_count += 1
        self.message_user(request, f"{created_count} lien(s) permanent(s) généré(s).", messages.SUCCESS)


@admin.register(UploadRequest)
class UploadRequestAdmin(admin.ModelAdmin):
    list_display = ('company', 'token_snippet', 'deposit_link_display', 'created_at', 'expires_at', 'status_badge', 'is_revoked')
    list_filter = ('is_revoked', 'created_at')
    search_fields = ('company__name', 'token')
    readonly_fields = ('token', 'created_at', 'revoked_at', 'last_accessed_at', 'full_link_preview')
    actions = ['revoke_selected_links']

    def token_snippet(self, obj):
        return f"{obj.token[:8]}..."
    token_snippet.short_description = "Token"

    def deposit_link_display(self, obj):
        url = obj.get_deposit_url()
        return format_html('<a href="{}" target="_blank">Accéder</a>', url)
    deposit_link_display.short_description = "Lien"

    def status_badge(self, obj):
        if obj.is_valid():
            return format_html('<span style="color:#16a34a; font-weight:bold;">Valide</span>')
        if obj.is_revoked:
            return format_html('<span style="color:#dc2626; font-weight:bold;">Révoqué</span>')
        return format_html('<span style="color:#d97706; font-weight:bold;">Expiré</span>')
    status_badge.short_description = "Validité"

    def full_link_preview(self, obj):
        if not obj.pk:
            return "-"
        return obj.get_deposit_url()
    full_link_preview.short_description = "Chemin relatif du lien"

    @admin.action(description="Révoquer immédiatement les liens sélectionnés")
    def revoke_selected_links(self, request, queryset):
        updated = 0
        for req in queryset.filter(is_revoked=False):
            req.revoke(reason=f"Révoqué par l'administrateur ({request.user.username})")
            updated += 1
        self.message_user(request, f"{updated} lien(s) révoqué(s).", messages.WARNING)


@admin.register(SubmittedDocument)
class SubmittedDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'submitted_at',
        'company',
        'requirement',
        'original_filename',
        'status_badge',
        'file_size_display',
        'detected_mime_type',
        'has_usable_text',
        'storage_backend',
        'drive_status'
    )
    list_filter = ('status', 'requirement', 'storage_backend', 'has_usable_text', 'submitted_at')
    search_fields = ('company__name', 'original_filename', 'normalized_filename', 'drive_file_id')
    readonly_fields = (
        'submitted_at',
        'company',
        'requirement',
        'upload_request',
        'original_filename',
        'normalized_filename',
        'file_size_bytes',
        'detected_mime_type',
        'status',
        'technical_check_results',
        'extracted_text_char_count',
        'has_usable_text',
        'extracted_text_preview',
        'storage_backend',
        'drive_file_id',
        'drive_folder_id',
        'local_archive_path',
        'error_message',
        'archived_at'
    )

    def status_badge(self, obj):
        return _render_status_badge(obj.status)
    status_badge.short_description = "Statut"

    def file_size_display(self, obj):
        if not obj.file_size_bytes:
            return "0 Ko"
        if obj.file_size_bytes >= 1024 * 1024:
            return f"{obj.file_size_bytes / (1024 * 1024):.1f} Mo"
        return f"{obj.file_size_bytes / 1024:.0f} Ko"
    file_size_display.short_description = "Taille"

    def drive_status(self, obj):
        if obj.storage_backend == 'google_drive' and obj.drive_file_id:
            return format_html('<span style="color:#15803d; font-weight:600;">Drive OK</span>')
        if obj.storage_backend == 'local_archive' and obj.local_archive_path:
            return format_html('<span style="color:#0284c7; font-weight:600;">Archive locale</span>')
        return format_html('<span style="color:#9ca3af;">Non archivé</span>')
    drive_status.short_description = "Archivage"

    def extracted_text_preview(self, obj):
        if not obj.extracted_text:
            return format_html('<em>Aucun texte extrait</em>')
        preview = obj.extracted_text[:1000]
        if len(obj.extracted_text) > 1000:
            preview += "\n... [texte tronqué]"
        return format_html('<pre style="white-space:pre-wrap; max-height:300px; overflow-y:auto; background:#f8fafc; padding:10px; border:1px solid #e2e8f0; border-radius:6px;">{}</pre>', preview)
    extracted_text_preview.short_description = "Aperçu du texte extrait"
