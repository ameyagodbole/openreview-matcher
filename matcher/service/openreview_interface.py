import re
import openreview
import logging

def build_edge(invitation, forum_id, reviewer, score, label, number):
    '''
    Helper function for constructing an openreview.Edge object.
    Readers, nonreaders, writers, and signatures are automatically filled based on the invitaiton.
    '''
    return openreview.Edge(
        head = forum_id,
        tail = reviewer,
        weight = score,
        label = label,
        invitation = invitation.id,
        readers = _get_values(invitation, number, 'readers'),
        nonreaders = _get_values(invitation, number, 'nonreaders'),
        writers = _get_values(invitation, number, 'writers'),
        signatures = _get_values(invitation, number, 'signatures'))

def _get_values(invitation, number, property):
    '''Return values compatible with the field `property` in invitation.reply.content'''
    values = []

    property_params = invitation.reply.get(property, {})
    if 'values' in property_params:
        values = property_params.get('values', [])
    elif 'values-regex' in property_params:
        regex_pattern = property_params['values-regex']
        values = []

        for group_id in regex_pattern.split('|'):
            group_id = group_id.replace('^', '').replace('$', '')
            if 'Paper.*' in group_id:
                group_id = group_id.replace('Paper.*', 'Paper{}'.format(number))

    return values

def _edge_to_score(edge, translate_map=None):
    '''
    Given an openreview.Edge, and a mapping defined by `translate_map`,
    return a numeric score, given an Edge.
    '''

    score = edge.weight

    if translate_map:
        try:
            score = translate_map[edge.label]
        except KeyError:
            raise EncoderError(
                'Cannot translate label {} to score. Valid labels are: {}'.format(
                    edge.label, translate_map.keys()))

    if not isinstance(score, float) and not isinstance(score, int):
        try:
            score = float(score)
        except ValueError:
            raise EncoderError(
                'Edge {} has weight that is neither float nor int: {}, type {}'.format(
                    edge.id, edge.weight, type(edge.weight)))

    return score

def get_all_edges(client, edge_invitation_id, logger=None):
    '''Helper function for retrieving and parsing all edges in bulk'''

    all_edges = []
    edge_invitation = client.get_invitation(edge_invitation_id)

    edges_grouped_by_paper = client.get_grouped_edges(
        invitation=edge_invitation_id,
        groupby='head',
        select='tail,label,weight'
    )

    for group in edges_grouped_by_paper:
        forum_id = group['id']['head']
        for group_value in group['values']:
            all_edges.append(build_edge(
                edge_invitation,
                forum_id,
                group_value['tail'],
                group_value.get('weight'),
                group_value.get('label'),
                None
            ))
    return all_edges

class ConfigNoteInterface:
    def __init__(self, client, config_note_id, logger=logging.getLogger(__name__), cache=None):
        self.client = client
        self.config_note_id = config_note_id
        self.logger = logger
        self._cache = {} if not cache else cache

        for invitation_id in self.config_note.content.get('scores_specification', {}):
            try:
                self.client.get_invitation(invitation_id)
            except openreview.OpenReviewException as error_handle:
                self.set_status('Error')
                raise error_handle


    @property
    def match_group(self):
        if not 'match_group' in self._cache:
            self._cache['match_group'] = self.client.get_group(
                self.config_note.content['match_group'])

        return self._cache['match_group']

    @property
    def reviewers(self):
        return self.match_group.members

    @property
    def config_note(self):
        if not 'config_note' in self._cache:
            self._cache['config_note'] = self.client.get_note(self.config_note_id)

        return self._cache['config_note']

    @property
    def paper_notes(self):
        if not 'paper_notes' in self._cache:
            self._cache['paper_notes'] = list(openreview.tools.iterget_notes(
                self.client, invitation=self.config_note.content['paper_invitation']))

        return self._cache['paper_notes']

    @property
    def papers(self):
        return [note.id for note in self.paper_notes]

    @property
    def minimums(self):
        if not 'minimums' in self._cache:
            minimums, maximums = self._get_quota_arrays()
            self._cache['minimums'] = minimums
            self._cache['maximums'] = maximums

        return self._cache['minimums']

    @property
    def maximums(self):
        if not 'maximums' in self._cache:
            minimums, maximums = self._get_quota_arrays()
            self._cache['minimums'] = minimums
            self._cache['maximums'] = maximums

        return self._cache['maximums']

    @property
    def demands(self):
        if not 'demands' in self._cache:
            self._cache['demands'] = [int(self.config_note.content['max_users']) for paper in self.papers]

        return self._cache['demands']

    @property
    def num_alternates(self):
        return int(self.config_note.content['alternates'])

    @property
    def constraints(self):
        if not 'constraint_edges' in self._cache:
            self._cache['constraint_edges'] = get_all_edges(
                self.client, self.config_note.content['conflicts_invitation'], logger=self.logger)

        for edge in self._cache['constraint_edges']:
            yield edge.head, edge.tail, edge.weight

    @property
    def scores_by_type(self):
        scores_specification = self.config_note.content.get('scores_specification', {})

        if not 'edges_by_invitation' in self._cache:
            edges_by_invitation = {}
            for invitation_id in scores_specification.keys():
                edges_by_invitation[invitation_id] = get_all_edges(
                    self.client, invitation_id, logger=self.logger)

            self._cache['edges_by_invitation'] = edges_by_invitation

        translate_maps = {
            inv_id: score_spec['translate_map'] \
            for inv_id, score_spec in scores_specification.items() \
            if 'translate_map' in score_spec
        }

        return {
            inv_id: [
                (
                    edge.head,
                    edge.tail,
                    _edge_to_score(edge, translate_map=translate_maps.get(inv_id))
                ) for edge in edges] \
            for inv_id, edges in self._cache['edges_by_invitation'].items() \
        }

    @property
    def weight_by_type(self):
        scores_specification = self.config_note.content.get('scores_specification', {})
        return {
            inv_id: entry['weight'] \
            for inv_id, entry in scores_specification.items()
        }

    @property
    def assignment_invitation(self):
        if 'assignment_invitation' not in self._cache:
            self._cache['assignment_invitation'] = self.client.get_invitation(
                self.config_note.content['assignment_invitation'])

        return self._cache['assignment_invitation']

    @property
    def aggregate_score_invitation(self):
        if 'aggregate_score_invitation' not in self._cache:
            self._cache['aggregate_score_invitation'] = self.client.get_invitation(
                self.config_note.content['aggregate_score_invitation'])

        return self._cache['aggregate_score_invitation']

    @property
    def custom_load_edges(self):
        if 'custom_load_edges' not in self._cache:
            self._cache['custom_load_edges'] = get_all_edges(
                self.client, self.config_note.content['custom_load_invitation'], logger=self.logger)

        return self._cache['custom_load_edges']

    def set_status(self, status, message=''):
        '''Set the status of the config note'''
        self.config_note.content['status'] = status

        if message:
            self.config_note.content['error_message'] = message

        self._cache['config_note'] = self.client.post_note(self.config_note)
        self.logger.debug('status set to: {}'.format(self.config_note.content['status']))

    def set_assignments(self, assignments_by_forum):
        '''Helper function for posting assignments returned by the Encoder'''
        label = self.config_note.content['title']
        paper_by_forum = {n.forum: n for n in self.paper_notes}

        self.logger.debug('saving {} edges'.format(self.assignment_invitation.id))

        assignment_edges = []
        score_edges = []

        for forum, assignments in assignments_by_forum.items():
            paper = paper_by_forum[forum]
            for paper_user_entry in assignments:
                score = paper_user_entry['aggregate_score']
                user = paper_user_entry['user']

                assignment_edges.append(
                    build_edge(
                        self.assignment_invitation,
                        forum,
                        user,
                        score,
                        label,
                        paper.number
                    )
                )

                score_edges.append(
                    build_edge(
                        self.aggregate_score_invitation,
                        forum,
                        user,
                        score,
                        label,
                        paper.number
                    )
                )

        openreview.tools.post_bulk_edges(self.client, assignment_edges)
        openreview.tools.post_bulk_edges(self.client, score_edges)
        self.logger.debug('posted {} assignment edges'.format(len(assignment_edges)))
        self.logger.debug('posted {} aggregate score edges'.format(len(score_edges)))

    def set_alternates(self, alternates_by_forum):
        '''Helper function for posting alternates returned by the Encoder'''

        label = self.config_note.content['title']

        paper_by_forum = {n.forum: n for n in self.paper_notes}

        score_edges = []
        for forum, assignments in alternates_by_forum.items():
            paper = paper_by_forum[forum]

            for paper_user_entry in assignments:
                score = paper_user_entry['aggregate_score']
                user = paper_user_entry['user']

                score_edges.append(
                    build_edge(
                        self.aggregate_score_invitation,
                        forum,
                        user,
                        score,
                        label,
                        paper.number
                    )
                )

        openreview.tools.post_bulk_edges(self.client, score_edges)
        self.logger.debug('posted {} aggregate score edges for alternates'.format(len(score_edges)))

    def _get_quota_arrays(self):
        '''get `minimum` and `maximum` reviewer load arrays, accounting for custom loads'''
        minimums = [int(self.config_note.content['min_papers']) for r in self.reviewers]
        maximums = [int(self.config_note.content['max_papers']) for r in self.reviewers]

        for edge in self.custom_load_edges:
            try:
                custom_load = int(edge.weight)
            except ValueError:
                raise MatcherError('invalid custom load weight')

            if custom_load < 0:
                custom_load = 0

            index = self.reviewers.index(edge.tail)
            maximums[index] = custom_load

            if custom_load < minimums[index]:
                minimums[index] = custom_load

        return minimums, maximums