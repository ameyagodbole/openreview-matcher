class BadTokenException (Exception):
    pass

class NoTokenException (Exception):
    pass

class AlreadyRunningException (Exception):
    pass

class AlreadyCompleteException (Exception):
    pass

class NotFoundError (Exception):
    pass

class TranslateScoreError (Exception):
    pass

class ScoreEdgeMissingWeightError (Exception):
    pass