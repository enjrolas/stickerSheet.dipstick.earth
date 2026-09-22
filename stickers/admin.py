from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers as admin_helpers
from django.utils.html import format_html

from . import shapes
from .models import Species, Sticker


@admin.register(Species)
class SpeciesAdmin(admin.ModelAdmin):
    list_display = ('common_name', 'scientific_name', 'group', 'published_count')
    list_filter = ('group',)
    search_fields = ('common_name', 'scientific_name')
    prepopulated_fields = {'slug': ('common_name',)}


class BinFilter(admin.SimpleListFilter):
    """
    The admin lists from `all_objects`, so deleted stickers are reachable and
    restorable. This filter defaults to hiding them, which is what the default
    manager would have done anyway.
    """

    title = 'bin'
    parameter_name = 'bin'

    def lookups(self, request, model_admin):
        return (('live', 'Live (default)'), ('deleted', 'In the bin'),
                ('all', 'Everything'))

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'deleted':
            return queryset.filter(deleted_at__isnull=False)
        if value == 'all':
            return queryset
        return queryset.filter(deleted_at__isnull=True)

    def choices(self, changelist):
        # Mark "Live" as selected when no explicit choice has been made.
        for choice in super().choices(changelist):
            if choice['query_string'] == '?' and self.value() is None:
                choice['selected'] = False
            yield choice


@admin.register(Sticker)
class StickerAdmin(admin.ModelAdmin):
    """
    The moderation queue. Public submissions arrive as `pending`; nothing is
    on the sheet until it is `published`.
    """

    list_display = ('preview', 'species', 'wildlife_investigator', 'location',
                    'status', 'binned', 'created_at')
    list_display_links = ('preview', 'species')
    list_filter = (BinFilter, 'status', 'media_kind', 'species__group',
                   'created_at')
    search_fields = ('species__common_name', 'wildlife_investigator',
                     'location', 'caption')
    autocomplete_fields = ('species',)
    readonly_fields = ('media_kind', 'latitude', 'longitude', 'created_at',
                       'updated_at', 'big_preview', 'submitter_email',
                       'deleted_at')
    actions = ('publish', 'reject', 'restore', 'rebuild_derivatives')
    date_hierarchy = 'created_at'
    list_per_page = 40

    fieldsets = (
        ('Moderation', {
            'fields': ('status', 'moderator_note', 'submitter_email',
                       'deleted_at'),
        }),
        ('The capture', {
            'fields': ('big_preview', 'media', 'media_kind', 'species',
                       'caption', 'shape'),
        }),
        ('Credit and place', {
            'fields': ('wildlife_investigator', 'location', 'latitude',
                       'longitude', 'captured_at'),
        }),
        ('Housekeeping', {
            'classes': ('collapse',),
            'fields': ('slug', 'created_at', 'updated_at'),
        }),
    )

    def get_queryset(self, request):
        # all_objects, so a soft-deleted sticker can still be found and
        # restored. BinFilter hides them from the default view.
        return Sticker.all_objects.get_queryset().select_related('species')

    @admin.display(description='In bin', boolean=True)
    def binned(self, obj):
        return obj.is_deleted

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # Populate the shape dropdown from the SVGs actually on disk, so
        # dropping a new outline into stickers/shapes/ needs no migration.
        if db_field.name == 'shape':
            kwargs['widget'] = forms.Select(
                choices=[('', 'Auto (spread across the sheet)')]
                        + shapes.available())
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(description='Sticker')
    def preview(self, obj):
        url = obj.thumb_url
        if not url:
            return '—'
        return format_html(
            '<img src="{}" style="width:56px;height:56px;object-fit:cover;'
            'border-radius:12px;border:2px solid #141210">', url)

    @admin.display(description='Preview')
    def big_preview(self, obj):
        if not obj.pk or not obj.media:
            return 'Save first to generate the sticker.'
        sticker = obj.sticker_url
        if not sticker:
            return '—'
        return format_html(
            '<div style="display:flex;gap:16px;align-items:flex-start">'
            '<img src="{}" style="width:220px;background:#fbf6ec;'
            'padding:8px;border-radius:8px">'
            '<a href="{}" download style="align-self:center">Download PNG</a>'
            '</div>', sticker, sticker)

    @admin.action(description='Publish selected stickers to the sheet')
    def publish(self, request, queryset):
        updated = queryset.update(status=Sticker.Status.PUBLISHED)
        self.message_user(request, '%d sticker(s) published.' % updated)

    @admin.action(description='Reject selected stickers')
    def reject(self, request, queryset):
        updated = queryset.update(status=Sticker.Status.REJECTED)
        self.message_user(request, '%d sticker(s) rejected.' % updated)

    @admin.action(description='Restore selected stickers from the bin')
    def restore(self, request, queryset):
        # Resolve the selection from the POST rather than from `queryset`.
        # On the default changelist BinFilter has already excluded every
        # binned row, so `queryset` would be empty here and the action would
        # silently do nothing — the one case you actually want it to work.
        pks = request.POST.getlist(admin_helpers.ACTION_CHECKBOX_NAME) or list(
            queryset.values_list('pk', flat=True))
        restored = Sticker.all_objects.filter(
            pk__in=pks, deleted_at__isnull=False).restore()
        if restored:
            self.message_user(request, '%d sticker(s) restored.' % restored)
        else:
            self.message_user(request,
                              'Nothing to restore — none of those are in the bin.',
                              level=messages.WARNING)

    @admin.action(description='Rebuild sticker PNG / thumbnails')
    def rebuild_derivatives(self, request, queryset):
        for sticker in queryset:
            sticker.build_derivatives()
        self.message_user(request, 'Rebuilt %d sticker(s).' % queryset.count())


admin.site.site_header = 'dipstick sticker sheet'
admin.site.site_title = 'sticker sheet admin'
admin.site.index_title = 'Wildlife captured down a dipstick'
