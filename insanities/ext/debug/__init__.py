#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from insanities.web.core import Wrapper
from insanities.web.http import HttpException
from debug_dj import technical_500_response

import logging
logger = logging.getLogger(__name__)

class Debug(Wrapper):
    def handle(self, rctx, wrapped):
        try:
            rctx = wrapped(rctx)
        except HttpException, e:
            raise e
        except Exception, e:
            import httplib

            rctx.response.status = httplib.INTERNAL_SERVER_ERROR
            exc_info = sys.exc_info()
            html = technical_500_response(rctx, *exc_info)
            rctx.response.write(html)
            logger.exception(e)
        return rctx



