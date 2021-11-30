import sys
import re
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from elections.helpers import JsonPaginator, EEHelper
from elections.models import PostElection, Election, Post, VotingSystem
from people.models import Person, PersonPost


class YNRElectionImporter:
    """
    Takes a JSON object from YNR and creates or updates an election object
    from it.

    Manages caching, and updating metadata from EE

    """

    def __init__(self, ee_helper=None):
        if not ee_helper:
            ee_helper = EEHelper()
        self.ee_helper = ee_helper
        self.election_cache = {}

    def ballot_order(self, ballot_dict):
        charisma_map = {
            "ref": {"default": 100},
            "parl": {"default": 90},
            "europarl": {"default": 80},
            "mayor": {"default": 70, "local-authority": 65},
            "nia": {"default": 60},
            "gla": {"default": 60, "a": 55},
            "naw": {"default": 60, "r": 55},
            "senedd": {"default": 60, "r": 65, "c": 60},
            "sp": {"default": 60, "r": 55},
            "pcc": {"default": 70},
            "local": {"default": 40},
        }
        modifier = 0
        ballot_paper_id = ballot_dict["ballot_paper_id"]

        # Look up the dict of possible weights for this election type
        weights = charisma_map.get(
            ballot_paper_id.split(".")[0], {"default": 30}
        )

        organisation_type = ballot_paper_id.split(".")[0]
        default_weight_for_election_type = weights.get("default")
        base_charisma = weights.get(
            organisation_type, default_weight_for_election_type
        )

        # Look up `r` and `a` subtypes
        subtype = re.match(r"^[^.]+\.([ar])\.", ballot_paper_id)
        if subtype:
            base_charisma = weights.get(subtype.group(1), base_charisma)

        # by-elections are slightly less charismatic than scheduled elections
        if ".by." in ballot_paper_id:
            modifier += 1

        return base_charisma - modifier

    def update_or_create_from_ballot_dict(self, ballot_dict):
        created = False
        slug = ballot_dict["election"]["election_id"]

        election_weight = self.ballot_order(ballot_dict)
        if slug not in self.election_cache:
            election_type = slug.split(".")[0]

            election, created = Election.objects.update_or_create(
                slug=slug,
                election_type=election_type,
                defaults={
                    "election_date": ballot_dict["election"]["election_date"],
                    "name": ballot_dict["election"]["name"].strip(),
                    "current": ballot_dict["election"]["current"],
                    "election_weight": election_weight,
                    "uses_lists": ballot_dict["election"]["party_lists_in_use"],
                },
            )

            self.import_metadata_from_ee(election)
            self.election_cache[election.slug] = election
        return self.election_cache[slug]

    def import_metadata_from_ee(self, election):
        """
        There are various things we don't have in YNR, have in EE and want here

        This means grabbing the data from EE directly
        """
        ee_data = self.ee_helper.get_data(election.slug)
        if ee_data:
            updated = False
            metadata = ee_data["metadata"]
            if metadata:
                election.metadata = metadata
                updated = True

            description = ee_data["explanation"]
            if description:
                election.description = description
                updated = True

            voting_system = ee_data["voting_system"]
            if voting_system:
                election.voting_system = VotingSystem.objects.update_or_create(
                    slug=voting_system["slug"],
                    defaults={"name": voting_system["name"]},
                )[0]
                updated = True

            if updated:
                election.save()


class YNRPostImporter:
    def __init__(self, ee_helper=None):
        if not ee_helper:
            ee_helper = EEHelper()
        self.ee_helper = ee_helper
        self.post_cache = {}

    def update_or_create_from_ballot_dict(self, ballot_dict):
        # fall back to slug here as some temp ballots don't have an ID set
        post_id = ballot_dict["post"]["id"] or ballot_dict["post"]["slug"]
        if not post_id:
            # if no id to use return None to indicate to skip this ballot
            return None

        if post_id not in self.post_cache:
            post, _ = Post.objects.update_or_create(
                ynr_id=post_id,
                defaults={"label": ballot_dict["post"]["label"]},
            )
            self.post_cache[post_id] = post
        return self.post_cache[post_id]


class YNRBallotImporter:
    """
    Class for populating local election and ballot models in this
    project from YNR.

    The class sets up everything needed for show a ballot, including elections,
    posts, voting systems, and the person information that show's on a ballot.
    (name, candidacy data)

    """

    def __init__(
        self,
        force_update=False,
        stdout=sys.stdout,
        current_only=False,
        exclude_candidacies=False,
        force_metadata=False,
        force_current_metadata=False,
        recently_updated=False,
        base_url=None,
        default_params=None,
    ):
        self.stdout = stdout
        self.ee_helper = EEHelper()
        self.voting_systems = {}
        self.election_importer = YNRElectionImporter(self.ee_helper)
        self.post_importer = YNRPostImporter(self.ee_helper)
        self.force_update = force_update
        self.current_only = current_only
        self.exclude_candidacies = exclude_candidacies
        self.force_metadata = force_metadata
        self.force_current_metadata = force_current_metadata
        self.recently_updated = recently_updated
        self.base_url = base_url or settings.YNR_BASE
        self.default_params = default_params or {"page_size": 200}

    def get_paginator(self, page1):
        return JsonPaginator(page1, self.stdout)

    def get_last_updated(self):
        try:
            return PostElection.objects.last_updated_in_ynr().ynr_modified
        except PostElection.DoesNotExist:
            # default before changes were added to YNR
            return timezone.datetime(2021, 10, 27, tzinfo=timezone.utc)

    @property
    def should_prewarm_ee_cache(self):
        """
        Always if current_only, otherwise check if params or is a
        recent updates only
        """
        if self.current_only:
            return True

        return not any([self.params, self.recently_updated])

    @property
    def is_full_import(self):
        """
        Check if any flags or paras
        """
        return not any([self.recently_updated, self.current_only, self.params])

    def build_params(self, params):
        """
        Build up params based on flages initialised with or return an
        empty dict
        """
        params = params or {}
        if self.current_only:
            params["current"] = True

        if self.recently_updated:
            params["last_updated"] = self.get_last_updated().isoformat()

        if params:
            params.update(self.default_params)

        return params

    @property
    def import_url(self):
        """
        Use cached data if a full import, unless base_url is using locahost
        """
        if self.is_full_import and not self.base_url.startswith(
            "http://localhost"
        ):
            return (
                f"{self.base_url}/media/cached-api/latest/ballots-000001.json"
            )

        querystring = urlencode(self.params)
        return f"{self.base_url}/api/next/ballots/?{querystring}"

    @property
    def should_run_post_ballot_import_tasks(self):
        """
        Don't try to do things like add replaced
        ballots if we've filtered the ballots.
        This is because there's a high chance we've not
        got all the ballots we need yet.
        """
        return any([self.is_full_import, self.current_only])

    def do_import(self, params=None):
        self.params = self.build_params(params=params)
        if self.should_prewarm_ee_cache:
            self.ee_helper.prewarm_cache(current=not self.force_metadata)

        pages = self.get_paginator(self.import_url)
        for page in pages:
            self.add_ballots(page)

        if self.should_run_post_ballot_import_tasks:
            self.attach_cancelled_ballot_info()

        self.delete_orphan_posts()

    def delete_orphan_posts(self):
        """
        This method cleans orphan posts.
        This typically gets called at the end of the import process.
        """
        return Post.objects.filter(postelection=None).delete()

    def add_replaced_ballot(self, ballot, replaced_ballot_id):
        """
        Takes a ballot object and a ballot_paper_id for a ballot that
        has been replaced. If the replaced ballot is found, adds this
        relationship. Explicity return True or False to represent if
        the lookup was a success and help with testing.
        """
        if not replaced_ballot_id:
            return False

        try:
            replaced_ballot = PostElection.objects.get(
                ballot_paper_id=replaced_ballot_id,
            )
        except PostElection.DoesNotExist:
            return False

        ballot.replaces.add(replaced_ballot)
        return True

    @transaction.atomic()
    def add_ballots(self, results):
        for ballot_dict in results["results"]:
            print(ballot_dict["ballot_paper_id"])

            election = self.election_importer.update_or_create_from_ballot_dict(
                ballot_dict
            )

            post = self.post_importer.update_or_create_from_ballot_dict(
                ballot_dict
            )
            if not post:
                # cant create a ballot without a post so skip to the next one
                continue

            defaults = {
                "election": election,
                "post": post,
                "winner_count": ballot_dict["winner_count"],
                "cancelled": ballot_dict["cancelled"],
                "locked": ballot_dict["candidates_locked"],
            }

            if ballot_dict["candidates_locked"] and ballot_dict["winner_count"]:
                defaults["contested"] = (
                    len(ballot_dict["candidacies"])
                    > ballot_dict["winner_count"]
                )

            # only update this when using the recently_updated flag as otherwise
            # the timestamp will only be the modifed timestamp on the ballot
            # see BallotSerializer.get_last_updated in YNR
            if self.recently_updated:
                defaults["ynr_modified"] = ballot_dict["last_updated"]

            ballot, created = PostElection.objects.update_or_create(
                ballot_paper_id=ballot_dict["ballot_paper_id"],
                defaults=defaults,
            )

            if self.recently_updated:
                # we can do this as the older ballot will be known.
                # if the ballot is does not replace another ballot,
                # nothing happens
                self.add_replaced_ballot(
                    ballot=ballot,
                    replaced_ballot_id=ballot_dict.get("replaces"),
                )

            if ballot.election.current or self.force_metadata:
                self.import_metadata_from_ee(ballot)

            if not self.exclude_candidacies:
                # Now set the nominations up for this ballot
                # First, remove any old candidates, this is to flush out candidates
                # that have changed. We just delete the `person_post`
                # (`membership` in YNR), not the person profile.
                ballot.personpost_set.all().delete()
                for candidate in ballot_dict["candidacies"]:
                    person, person_created = Person.objects.update_or_create(
                        ynr_id=candidate["person"]["id"],
                        defaults={"name": candidate["person"]["name"]},
                    )
                    result = candidate["result"] or {}
                    # if we dont have a result, get the "elected" value from
                    # the main candidacy data
                    elected = result.get("elected", candidate["elected"])

                    PersonPost.objects.create(
                        post_election=ballot,
                        person=person,
                        party_id=candidate["party"]["legacy_slug"],
                        party_name=candidate["party_name"],
                        party_description_text=candidate[
                            "party_description_text"
                        ],
                        list_position=candidate["party_list_position"],
                        elected=elected,
                        votes_cast=result.get("num_ballots", None),
                        post=ballot.post,
                        election=ballot.election,
                    )

            if created:
                self.stdout.write(
                    "Added new ballot: {0}".format(ballot.ballot_paper_id)
                )

    def import_metadata_from_ee(self, ballot):
        # First, grab the data from EE

        self.set_territory(ballot)
        self.set_voting_system(ballot)
        self.set_metadata(ballot)
        self.set_organisation_type(ballot)
        self.set_division_type(ballot)
        ballot.save()

    def set_territory(self, ballot):
        if ballot.post.territory and not self.force_update:
            return
        ee_data = self.ee_helper.get_data(ballot.ballot_paper_id)
        if ee_data and "organisation" in ee_data:
            territory = ee_data["organisation"].get("territory_code", "-")
        else:
            territory = "-"

        ballot.post.territory = territory
        ballot.post.save()

    def set_voting_system(self, ballot):
        if ballot.voting_system_id and not self.force_update:
            return
        ee_data = self.ee_helper.get_data(ballot.ballot_paper_id)
        if ee_data and "voting_system" in ee_data:
            voting_system_slug = ee_data["voting_system"]["slug"]
            if not voting_system_slug in self.voting_systems:
                voting_system = VotingSystem.objects.update_or_create(
                    slug=voting_system_slug,
                    defaults={"description": ee_data["voting_system"]["name"]},
                )[0]
                self.voting_systems[voting_system_slug] = voting_system

            ballot.voting_system = self.voting_systems[voting_system_slug]
            ballot.save()

    def set_metadata(self, ballot):
        if not self.force_current_metadata:
            if ballot.metadata and not self.force_update:
                return
        ee_data = self.ee_helper.get_data(ballot.ballot_paper_id)
        if ee_data:
            ballot.metadata = ee_data["metadata"]

    def set_organisation_type(self, ballot):
        if ballot.post.organization_type and not self.force_update:
            return
        ee_data = self.ee_helper.get_data(ballot.ballot_paper_id)
        if ee_data:
            ballot.post.organization_type = ee_data["organisation"][
                "organisation_type"
            ]
            ballot.post.save()

    def set_division_type(self, ballot):
        """
        Attempts to set the division_type field from EveryElection
        """
        if ballot.post.division_type and not self.force_update:
            return

        ee_data = self.ee_helper.get_data(ballot.ballot_paper_id)

        if not ee_data or not ee_data["division"]:
            return

        ballot.post.division_type = ee_data["division"].get("division_type")
        # ensures the division_type is valid, or will raise a ValidationError
        ballot.post.full_clean()
        ballot.post.save()

    def get_replacement_ballot(self, ballot_id):
        replacement_ballot = None
        ee_data = self.ee_helper.get_data(ballot_id)
        if ee_data:
            replacement_ballot_id = ee_data["replaced_by"]
            if replacement_ballot_id:
                try:
                    replacement_ballot = PostElection.objects.get(
                        ballot_paper_id=replacement_ballot_id
                    )
                except PostElection.DoesNotExist:
                    pass
        return replacement_ballot

    def attach_cancelled_ballot_info(self):
        # we need to do this as a post-process instead of in the manager
        # because if we're going to link 2 PostElection objects together
        # we need to be sure that both of them already exist in our DB
        cancelled_ballots = PostElection.objects.filter(cancelled=True)
        if self.current_only:
            cancelled_ballots = cancelled_ballots.filter(election__current=True)
        for cb in cancelled_ballots:
            cb.replaced_by = self.get_replacement_ballot(cb.ballot_paper_id)
            # Always get metadata, even if we might have it already.
            # This is because is self.force_update is False, it might not have
            # been imported already
            self.set_metadata(cb)
            cb.save()
