"""
Every license can be identified by a URL, e.g. "http://creativecommons.org/licenses/by-nc-sa/4.0/"
or "http://creativecommons.org/licenses/by-nc-nd/2.0/tw/".  In the RDF, this is the rdf:about
attribute on the cc:License element.

If a license has a child dc:source element, then this license is a translation of the license
with the url in the dc:source's rdf:resource attribute.

Some licenses ahve a dcq:isReplacedBy element.

"""
import os
import string
from copy import deepcopy

import polib
from django.conf import settings
from django.db import models
from django.utils import translation

from i18n import DEFAULT_LANGUAGE_CODE
from i18n.translation import get_translation_object
from licenses import FREEDOM_LEVEL_MAX, FREEDOM_LEVEL_MID, FREEDOM_LEVEL_MIN
from licenses.templatetags.license_tags import build_deed_url, build_license_url
from licenses.transifex import TransifexHelper

MAX_LANGUAGE_CODE_LENGTH = 8


class LegalCode(models.Model):
    license = models.ForeignKey(
        "licenses.License", on_delete=models.CASCADE, related_name="legal_codes"
    )
    language_code = models.CharField(
        max_length=MAX_LANGUAGE_CODE_LENGTH,
        help_text="E.g. 'en', 'en-ca', 'sr-Latn', or 'x-i18n'. Case-sensitive?",
    )
    html_file = models.CharField(
        max_length=300, help_text="HTML file we got this from", blank=True, default=""
    )

    translation_last_update = models.DateTimeField(
        help_text="The last_updated field from Transifex for this translation",
        null=True,
        default=None,
    )

    class Meta:
        ordering = ["license__about"]

    def __str__(self):
        return f"LegalCode<{self.language_code}, {self.license.about}>"

    def branch_name(self):
        """
        If this translation is modified, what is the name of the GitHub branch
        we'll use to manage the modifications?
        Basically its "{license code}-{version}-{language}[-{jurisdiction code}",
        except that all the "by* 4.0" licenses use "cc4" for the license_code part.
        This has to be a valid DNS domain, so we also change any _ to - and
        remove any periods.
        """
        license = self.license
        parts = []
        if license.license_code.startswith("by") and license.version == "4.0":
            parts.append("cc4")
        else:
            parts.extend([license.license_code, license.version])
        parts.append(self.language_code)
        if license.jurisdiction_code:
            parts.append(license.jurisdiction_code)
        return "-".join(parts).replace("_", "-").replace(".", "").lower()

    def license_url(self):
        """
        URL to view this translation of this license
        """
        license = self.license
        return build_license_url(
            license.license_code,
            license.version,
            license.jurisdiction_code,
            self.language_code,
        )

    def deed_url(self):
        """
        URL to view this translation of this deed
        """
        license = self.license
        return build_deed_url(
            license.license_code,
            license.version,
            license.jurisdiction_code,
            self.language_code,
        )

    def fat_code(self):
        """
        Returns e.g. 'CC BY-SA 4.0' - all upper case etc. No language.
        """
        return self.license.fat_code()

    def downstreams(self):
        """
        For use in e.g. templates, returns an iterable of dictionaries
        of the items in the downstream recipients section for this license.
        Each dictionary looks like:
            {
                "id": "s2a5A",
                "msgid_name": "s2a5A_defitnition_trnsla_name",
                "msgid_text": "s2a5A_defitnition_trnsla_text",
            }
        """
        expected_downstreams = [
            "offer",
            "no_restrictions",
        ]
        if self.license.license_code in ["by-sa", "by-nc-sa"]:
            expected_downstreams.insert(1, "adapted_material")
        LETTERS = string.ascii_uppercase
        translation = self.get_translation_object()
        # s2a5_license_grant_downstream_offer_name
        result = [
            {
                "id": f"s2a5{LETTERS[i]}_{item}",
                "msgid_name": f"s2a5_license_grant_downstream_{item}_name",
                "msgid_text": f"s2a5_license_grant_downstream_{item}_text",
            }
            for i, item in enumerate(expected_downstreams)
        ]
        for item in result:
            item["name_translation"] = translation.translate(item["msgid_name"])
            item["text_translation"] = translation.translate(item["msgid_text"])
        return result

    def definitions(self):
        """
        For use in e.g. templates, returns an iterable of dictionaries
        of the items in the definitions section for this license.
        Each dictionary looks like:
            {
                "id": "s1c",
                "msgid": "s1_defitnition_trnsla"
            }
        """
        license_code = self.license.license_code
        expected_definitions = [
            "adapted_material",
            "copyright_and_similar_rights",
            "effective_technological_measures",
            "exceptions_and_limitations",
            "licensed_material",
            "licensed_rights",
            "licensor",
            "share",
            "sui_generis_database_rights",
            "you",
        ]

        translation = self.get_translation_object()

        # now insert the optional ones
        def insert_after(after_this, what_to_insert):
            i = expected_definitions.index(after_this)
            expected_definitions.insert(i + 1, what_to_insert)

        if license_code == "by-sa":
            insert_after("adapted_material", "adapters_license")
            insert_after("adapters_license", "by_sa_compatible_license")
            insert_after("exceptions_and_limitations", "license_elements_sa")
        elif license_code == "by":
            insert_after("adapted_material", "adapters_license")
        elif license_code == "by-nc":
            insert_after("adapted_material", "adapters_license")
            insert_after("licensor", "noncommercial")
        elif license_code == "by-nd":
            pass
        elif license_code == "by-nc-nd":
            insert_after("licensor", "noncommercial")
        elif license_code == "by-nc-sa":
            insert_after("adapted_material", "adapters_license")
            insert_after("exceptions_and_limitations", "license_elements_nc_sa")
            insert_after("adapters_license", "by_nc_sa_compatible_license")
            insert_after("licensor", "noncommercial")

        LETTERS = string.ascii_lowercase
        result = [
            {"id": f"s1{LETTERS[i]}", "msgid": f"s1_definitions_{item}",}
            for i, item in enumerate(expected_definitions)
        ]
        for item in result:
            item["translation"] = translation.translate(item["msgid"])
        return result

    def get_translation_object(self):
        return get_translation_object(self.translation_filename(), self.language_code)

    def get_pofile(self) -> polib.POFile:
        # Piggy-back on the translation objects, which are cached as singletons for efficiency.
        return self.get_translation_object().pofile

    def get_english_pofile(self) -> polib.POFile:
        if self.language_code != DEFAULT_LANGUAGE_CODE:
            # Same license, just in English translation:
            english_legalcode = type(self).objects.get(
                license=self.license, language_code=DEFAULT_LANGUAGE_CODE
            )
            return english_legalcode.get_pofile()
        return self.get_pofile()

    def get_pofile_with_english_msgids(self) -> polib.POFile:
        """
        Get a pofile for this translation, but with the internal message keys replaced by the corresponding
        English messages. If this is English already, return a pofile with the English messages as keys
        and empty translations, as that's the expected content for an English pofile when English is the
        base language.
        """
        new_pofile = deepcopy(self.get_pofile())
        if self.language_code == DEFAULT_LANGUAGE_CODE:
            for entry in new_pofile:
                entry.msgid = entry.msgstr
                entry.msgstr = ""
            return new_pofile
        else:
            english_pofile = self.get_english_pofile()
            internal_key_to_english_message = {
                entry.msgid: entry.msgstr for entry in english_pofile
            }
            for entry in new_pofile:
                if entry.msgid not in internal_key_to_english_message:
                    raise ValueError(
                        f"Our English pofile has no message for the key {entry.msgid}, "
                        f"something is wrong with the translation files."
                    )
                entry.msgid = internal_key_to_english_message[entry.msgid]
            return new_pofile

    def translation_filename(self):
        """
        Return absolute path to the .po file with this translation.
        These are in the cc-licenses-data repository, in subdirectories:
          - "translations"
          - license code (all lowercase)
          - license version (e.g. 4.0, or "None" if not applicable)

        Within that directory, the files will be named "{lowercase_license_code}_{version}_{jurisdictiction}_{language_code}.po",
        except that if any part is not applicable, we'll leave out it and its separating "_" - e.g.
        for the BY-NC 4.0 French translation, which has no jurisdiction, the filename will be
        "by-nc_4.0_fr.po", and in full,
        "{translation repo topdir}/translations/by-nc/4.0/by-nc_4.0_fr.po".
        """
        license = self.license
        filename_parts = [
            license.license_code.lower(),
            license.version,
            license.jurisdiction_code,
            self.language_code,
        ]
        # Remove any empty parts
        filename_parts = [x for x in filename_parts if x]
        filename = "_".join(filename_parts) + ".po"
        subdir = f"{license.license_code.lower()}/{license.version or 'None'}"
        fullpath = os.path.join(
            settings.TRANSLATION_REPOSITORY_DIRECTORY, "translations", subdir, filename
        )
        return fullpath


class License(models.Model):
    about = models.URLField(
        max_length=200,
        help_text="The license's unique identifier, e.g. 'http://creativecommons.org/licenses/by-nd/2.0/br/'",
        unique=True,
    )
    license_code = models.CharField(
        max_length=40,
        help_text="shorthand representation for which class of licenses this falls into.  "
        "E.g. 'by-nc-sa', or 'MIT', 'nc-sampling+', 'devnations', ...",
    )
    version = models.CharField(
        max_length=3, help_text="E.g. '4.0'. Not required.", blank=True, default=""
    )
    jurisdiction_code = models.CharField(max_length=9, blank=True, default="")
    creator_url = models.URLField(
        max_length=200,
        blank=True,
        default="",
        help_text="E.g. http://creativecommons.org",
    )
    license_class_url = models.URLField(
        max_length=200,
        help_text="E.g. http://creativecommons.org/license/",
        blank=True,
        default="",
    )

    source = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="source_of",
        help_text="another license that this is the translation of",
    )

    is_replaced_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replaces",
        help_text="another license that has replaced this one",
    )
    is_based_on = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="base_of",
        help_text="another license that this one is based on",
    )

    deprecated_on = models.DateField(
        null=True, help_text="if set, the date on which this license was deprecated"
    )

    permits_derivative_works = models.BooleanField()
    permits_reproduction = models.BooleanField()
    permits_distribution = models.BooleanField()
    permits_sharing = models.BooleanField()

    requires_share_alike = models.BooleanField()
    requires_notice = models.BooleanField()
    requires_attribution = models.BooleanField()
    requires_source_code = models.BooleanField()

    prohibits_commercial_use = models.BooleanField()
    prohibits_high_income_nation_use = models.BooleanField()

    class Meta:
        ordering = ["-version", "license_code", "jurisdiction_code"]

    def __str__(self):
        return f"License<{self.about}>"

    def get_legalcode_for_language_code(self, language_code):
        """
        Return the legalcode for this license and language.
        If language_code has a "-" and we don't find it, try
        without the "-*" part (to handle e.g. "en-us").
        """
        if not language_code:
            language_code = translation.get_language()
        try:
            return self.legal_codes.get(language_code=language_code)
        except LegalCode.DoesNotExist:
            if "-" in language_code:  # e.g. "en-us"
                lang = language_code.split("-")[0]
                return self.legal_codes.get(language_code=lang)
            raise

    @property
    def resource_name(self):
        """Human-readable name for the translation resource for this license"""
        return self.fat_code()

    @property
    def resource_slug(self):
        # Transifex translation resource slug for this license.
        # letters, numbers, underscores or hyphens.
        if self.jurisdiction_code:
            slug = f"{self.license_code}_{self.version}_{self.jurisdiction_code}"
        else:
            slug = f"{self.license_code}_{self.version}"
        slug = slug.replace(".", "")
        return slug

    def rdf(self):
        """Generate RDF for this license?"""
        return "RDF Generation Not Implemented"  # FIXME if needed

    def fat_code(self):
        """
        Returns e.g. 'CC BY-SA 4.0' - all upper case etc. No language.
        """
        license = self
        s = f"{license.license_code} {license.version}"
        if license.license_code.startswith("by"):
            s = f"CC {s}"
        if license.jurisdiction_code:
            s = f"{s} {license.jurisdiction_code}"
        s = s.upper()
        return s

    def translated_title(self, language_code=None):
        legalcode = self.get_legalcode_for_language_code(language_code)
        translation_object = legalcode.get_translation_object()
        return translation_object.translations["license_medium"]

    @property
    def level_of_freedom(self):
        if self.license_code in ("devnations", "sampling"):
            return FREEDOM_LEVEL_MIN
        elif (
            self.license_code.find("sampling") > -1
            or self.license_code.find("nc") > -1
            or self.license_code.find("nd") > -1
        ):
            return FREEDOM_LEVEL_MID
        else:
            return FREEDOM_LEVEL_MAX

    @property
    def superseded(self):
        return self.is_replaced_by is not None

    @property
    def sampling_plus(self):
        return self.license_code in ("nc-sampling+", "sampling+")

    @property
    def include_share_adapted_material_clause(self):
        return self.license_code in ["by", "by-nc"]

    def tx_upload_messages(self):
        """
        Upload the messages to Transifex,
        creating the resource if it doesn't already exist.
        """
        # Have to do English first, they get uploaded differently as the "source" messages
        # and are required if we need to first create the resource in Transifex.
        en_legalcode = self.get_legalcode_for_language_code(DEFAULT_LANGUAGE_CODE)
        helper = TransifexHelper()
        helper.upload_messages_to_transifex(legalcode=en_legalcode)
        for legalcode in self.legal_codes.exclude(language_code=DEFAULT_LANGUAGE_CODE):
            helper.upload_messages_to_transifex(legalcode=legalcode)


class TranslatedLicenseName(models.Model):
    license = models.ForeignKey(License, related_name="names", on_delete=models.CASCADE)
    language_code = models.CharField(
        max_length=MAX_LANGUAGE_CODE_LENGTH,
        help_text="E.g. 'en', 'en-ca', 'sr-Latn', or 'x-i18n'. Case-sensitive?",
    )
    name = models.CharField(max_length=250, help_text="Translated name of license")

    class Meta:
        unique_together = [
            ("license", "language_code"),
        ]

    def __str__(self):
        return f"TranslatedLicenseName<{self.language_code}, {self.license}>"


class TranslationBranch(models.Model):
    branch_name = models.CharField(max_length=40)
    legalcodes = models.ManyToManyField("LegalCode")
    version = models.CharField(
        max_length=3, help_text="E.g. '4.0'. Not required.", blank=True, default=""
    )
    language_code = models.CharField(
        max_length=MAX_LANGUAGE_CODE_LENGTH,
        help_text="E.g. 'en', 'en-ca', 'sr-Latn', or 'x-i18n'. Case-sensitive?",
    )
    last_transifex_update = models.DateTimeField(
        "Time when translations related to this branch were last updated on Transifex "
        "that we know of.  If we see a newer last_update in Transifex, we need to update "
        "the git branch from the latest translation files, and then update this value "
        "to the most recent update time of those files.",
        null=True,
        blank=True,
    )
    complete = models.BooleanField(
        "There should only be one record per branch name with complete=False. There could "
        "be many with complete=True.",
        default=False,
    )
