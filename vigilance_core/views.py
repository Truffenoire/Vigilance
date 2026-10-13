"""
Vues de la plateforme Vigilance :
- Dépôt public partenaire sécurisé par jeton (sans compte requis).
- Tableau de bord de pilotage administrateur.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from django.db.models import Count, Q
from .models import Company, DocumentRequirement, UploadRequest, SubmittedDocument
from .services.pipeline import DocumentProcessingPipeline
from .services.validator import TechnicalValidationError


def public_deposit(request, token):
    """
    Interface publique responsive de dépôt de documents pour un partenaire.
    Accès strictement cloisonné à la seule entreprise détentrice du jeton.
    """
    upload_request = get_object_or_404(UploadRequest, token=token)

    # Vérification de la validité temporelle et du statut de révocation
    if not upload_request.is_valid():
        return render(request, 'vigilance/link_expired.html', {
            'upload_request': upload_request,
            'is_revoked': upload_request.is_revoked,
        }, status=403)

    # Mise à jour de la date de dernier accès
    upload_request.last_accessed_at = timezone.now()
    upload_request.save(update_fields=['last_accessed_at'])

    company = upload_request.company
    requirements = company.get_effective_requirements()

    if request.method == 'POST':
        action_type = request.POST.get('action_type', 'batch')
        success_list = []
        error_list = []
        warning_list = []
        files_processed_count = 0

        # Mode A : Dépôt groupé de plusieurs documents en une seule validation
        for req in requirements:
            field_name = f'file_{req.id}'
            uploaded_file = request.FILES.get(field_name)

            if uploaded_file:
                files_processed_count += 1
                try:
                    doc = DocumentProcessingPipeline.process_upload(
                        uploaded_file=uploaded_file,
                        company=company,
                        requirement=req,
                        upload_request=upload_request
                    )
                    if doc.status == SubmittedDocument.Status.ARCHIVE_DRIVE:
                        backend_str = "Google Drive" if doc.storage_backend == "google_drive" else "l'archive sécurisée"
                        success_list.append(f"« {req.name} » ({backend_str})")
                    elif doc.status == SubmittedDocument.Status.ERREUR:
                        error_list.append(f"« {req.name} » : {doc.error_message}")
                    else:
                        warning_list.append(f"« {req.name} » : {doc.get_status_display()}")
                except TechnicalValidationError as te:
                    error_list.append(f"« {req.name} » : rejet technique ({te.message})")
                except Exception as e:
                    error_list.append(f"« {req.name} » : incident technique ({str(e)})")

        # Mode B : Compatibilité avec l'upload individuel d'un document spécifique
        if files_processed_count == 0:
            single_req_id = request.POST.get('requirement_id')
            single_file = request.FILES.get('document_file')
            if single_req_id and single_file:
                try:
                    req = requirements.get(id=single_req_id)
                    files_processed_count += 1
                    doc = DocumentProcessingPipeline.process_upload(
                        uploaded_file=single_file,
                        company=company,
                        requirement=req,
                        upload_request=upload_request
                    )
                    if doc.status == SubmittedDocument.Status.ARCHIVE_DRIVE:
                        backend_str = "Google Drive" if doc.storage_backend == "google_drive" else "l'archive sécurisée"
                        success_list.append(f"« {req.name} » ({backend_str})")
                    elif doc.status == SubmittedDocument.Status.ERREUR:
                        error_list.append(f"« {req.name} » : {doc.error_message}")
                    else:
                        warning_list.append(f"« {req.name} » : {doc.get_status_display()}")
                except DocumentRequirement.DoesNotExist:
                    error_list.append("Catégorie de document non reconnue.")
                except TechnicalValidationError as te:
                    error_list.append(f"Rejet technique : {te.message}")
                except Exception as e:
                    error_list.append(f"Erreur d'analyse : {str(e)}")

        # Feedback à l'utilisateur
        if files_processed_count == 0:
            messages.error(request, "Veuillez sélectionner au moins un fichier avant de valider l'envoi.")
        else:
            if success_list:
                messages.success(
                    request,
                    f"✓ {len(success_list)} document(s) validé(s) et archivé(s) avec succès : " + ", ".join(success_list)
                )
            if warning_list:
                messages.info(request, "ℹ️ " + " | ".join(warning_list))
            if error_list:
                messages.error(request, "❌ " + " | ".join(error_list))

        return redirect('public_deposit', token=token)

    # Préparation des statuts des documents attendus pour l'affichage
    requirements_data = []
    for req in requirements:
        # Dernier document soumis avec succès ou en cours
        latest_doc = company.documents.filter(requirement=req).order_by('-submitted_at').first()
        requirements_data.append({
            'requirement': req,
            'latest_doc': latest_doc,
            'is_submitted': latest_doc is not None and latest_doc.status != SubmittedDocument.Status.ERREUR,
        })

    return render(request, 'vigilance/deposit.html', {
        'upload_request': upload_request,
        'company': company,
        'requirements_data': requirements_data,
        'max_size_mb': 10,
    })


@staff_member_required
def admin_dashboard(request):
    """
    Tableau de bord de synthèse pour l'administrateur.
    Présente les indicateurs clés du devoir de vigilance, le suivi des documents et les alertes.
    """
    total_companies = Company.objects.count()
    total_documents = SubmittedDocument.objects.count()

    # Décompte par statut
    status_counts = dict(
        SubmittedDocument.objects.values('status').annotate(total=Count('id')).values_list('status', 'total')
    )

    count_recu = status_counts.get(SubmittedDocument.Status.RECU, 0)
    count_format_valide = status_counts.get(SubmittedDocument.Status.FORMAT_VALIDE, 0)
    count_texte_extrait = status_counts.get(SubmittedDocument.Status.TEXTE_EXTRAIT, 0)
    count_archive = status_counts.get(SubmittedDocument.Status.ARCHIVE_DRIVE, 0)
    count_a_examiner = status_counts.get(SubmittedDocument.Status.A_EXAMINER, 0)
    count_erreur = status_counts.get(SubmittedDocument.Status.ERREUR, 0)

    # Documents récents
    recent_documents = SubmittedDocument.objects.select_related('company', 'requirement').order_by('-submitted_at')[:15]

    # Entreprises et leur taux de complétude
    companies_summary = []
    for comp in Company.objects.all():
        reqs = comp.get_effective_requirements()
        total_reqs = reqs.count()
        valid_docs = comp.documents.filter(
            status__in=[SubmittedDocument.Status.ARCHIVE_DRIVE, SubmittedDocument.Status.TEXTE_EXTRAIT]
        ).values('requirement').distinct().count()
        
        has_error = comp.documents.filter(status=SubmittedDocument.Status.ERREUR).exists()
        active_link = comp.get_active_upload_request()

        companies_summary.append({
            'company': comp,
            'total_reqs': total_reqs,
            'valid_docs': valid_docs,
            'is_complete': total_reqs > 0 and valid_docs >= total_reqs,
            'has_error': has_error,
            'active_link': active_link,
        })

    return render(request, 'vigilance/dashboard.html', {
        'total_companies': total_companies,
        'total_documents': total_documents,
        'count_recu': count_recu,
        'count_format_valide': count_format_valide,
        'count_texte_extrait': count_texte_extrait,
        'count_archive': count_archive,
        'count_a_examiner': count_a_examiner,
        'count_erreur': count_erreur,
        'recent_documents': recent_documents,
        'companies_summary': companies_summary,
    })
