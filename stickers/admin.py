from django.contrib import admin
from django.utils.html import format_html

from .models import Species, Sticker


@admin.register(Species)
class SpeciesAdmin(admin.ModelAdmin):
    list_display = ('common_name', 'scientific_name', 'group', 'published_count')
    list_filter = ('group',)
    search_fields = ('common_name', 'scientific_name')
    prepopulated_fields = {'slug': ('common_name',)}


@admin.register(Sticker)
class StickerAdmin(admin.ModelAdmin):
    """
    The moderation queue. Public submissions arrive as `pending`; nothing is
    on the sheet until it is `published`.
    """

    list_display = ('preview', 'species', 'wildlife_investigator', 'location',
                    'status', 'created_at')
    list_display_links = ('preview', 'species')
    list_filter = ('status', 'media_kind', 'species__group', 'created_at')
    search_fields = ('species__common_name', 'wildlife_investigator',
                     'location', 'caption')
    autocomplete_fields = ('species',)
    readonly_fields = ('media_kind', 'latitude', 'longitude', 'created_at',
                       'updated_at', 'big_preview', 'submitter_email')
    actions = ('publish', 'reject', 'rebuild_derivatives')
    date_hierarchy = 'created_at'
    list_per_page = 40

    fieldsets = (
        ('Moderation', {
            'fields': ('status', 'moderator_note', 'submitter_email'),
        }),
        ('The capture', {
            'fields': ('big_preview', 'media', 'media_kind', 'species',
                       'caption'),
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

    @admin.action(description='Rebuild sticker PNG / thumbnails')
    def rebuild_derivatives(self, request, queryset):
        for sticker in queryset:
            sticker.build_derivatives()
        self.message_user(request, 'Rebuilt %d sticker(s).' % queryset.count())


admin.site.site_header = 'dipstick sticker sheet'
admin.site.site_title = 'sticker sheet admin'
admin.site.index_title = 'Wildlife captured down a dipstick'
