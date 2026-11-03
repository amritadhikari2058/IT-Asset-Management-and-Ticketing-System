"""Backfill an initial revision for every existing knowledge-base article.

Existing articles stay published/draft/archived exactly as they were; they
simply gain revision 1 so history starts from a faithful snapshot instead of
an empty state. The migration is idempotent and reversible.
"""
from django.db import migrations

INITIAL_NOTE = "Initial version (migrated)"


def backfill_initial_revisions(apps, schema_editor):
    Article = apps.get_model("assets", "KnowledgeBaseArticle")
    Revision = apps.get_model("assets", "KnowledgeBaseArticleRevision")
    User = apps.get_model("accounts", "User")
    Category = apps.get_model("assets", "KnowledgeBaseCategory")

    for article in Article.objects.all().iterator():
        if Revision.objects.filter(article_id=article.pk).exists():
            continue
        category_name = ""
        if article.category_id:
            category = Category.objects.filter(pk=article.category_id).first()
            category_name = category.name if category else ""
        tags = list(
            article.tags.values("name", "slug").order_by("name"))
        editor_name = ""
        if article.author_id:
            author = User.objects.filter(pk=article.author_id).first()
            if author:
                editor_name = (
                    f"{author.first_name} {author.last_name}".strip()
                    or author.email)
        revision = Revision.objects.create(
            article_id=article.pk,
            revision_number=1,
            title=article.title,
            slug=article.slug,
            summary=article.summary or "",
            content=article.content or "",
            category_id=article.category_id,
            category_name=category_name,
            tags=tags,
            status=article.status,
            author_id=article.author_id,
            editor_id=article.author_id,
            editor_name=editor_name,
            change_note=INITIAL_NOTE,
        )
        # Preserve the article's real timeline rather than stamping "now".
        Revision.objects.filter(pk=revision.pk).update(
            created_at=article.updated_at)
        Article.objects.filter(pk=article.pk).update(
            revision_number=1, version=1)


def remove_initial_revisions(apps, schema_editor):
    Article = apps.get_model("assets", "KnowledgeBaseArticle")
    Revision = apps.get_model("assets", "KnowledgeBaseArticleRevision")
    Revision.objects.filter(change_note=INITIAL_NOTE).delete()
    Article.objects.update(revision_number=0, version=1)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0015_phase20_kb_versioning"),
    ]

    operations = [
        migrations.RunPython(
            backfill_initial_revisions, remove_initial_revisions),
    ]
