from flask import request, Response
from functools import wraps
from .encoders import register_default_decoders
from .encoders import register_default_encoders
from .errors import ErrorReason
from .errors import FlaskIOError
from .errors import MediaTypeSupported
from .errors import ValidationError
from .parsers import register_default_parsers


class FlaskIO(object):
    default_decoder = None
    default_encoder = None

    def __init__(self, app=None):
        self.__decoders = {}
        self.__encoders = {}
        self.__parsers = {}

        register_default_decoders(self)
        register_default_encoders(self)
        register_default_parsers(self)

        if app:
            self.init_app(app)

    def init_app(self, app):
        pass

    def register_decoder(self, media_type, func):
        if not self.default_decoder:
            self.default_decoder = media_type
        self.__decoders[media_type] = func

    def register_encoder(self, media_type, func):
        if not self.default_encoder:
            self.default_encoder = media_type
        self.__encoders[media_type] = func

    def register_parser(self, type_, func):
        self.__parsers[type_] = func

    def from_body(self, param_name, param_type, required=False, validate=None):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                self.__decode_into_param(kwargs, param_name, param_type, required, validate)
                return func(*args, **kwargs)
            return wrapper
        return decorator

    def from_cookie(self, param_name, param_type, default=None, required=False, multiple=False, validate=None, arg_name=None):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                self.__parse_into_param(kwargs, param_name, param_type, request.cookies, arg_name, default, required, multiple, validate)
                return func(*args, **kwargs)
            return wrapper
        return decorator

    def from_form(self, param_name, param_type, default=None, required=False, multiple=False, validate=None, arg_name=None):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                self.__parse_into_param(kwargs, param_name, param_type, request.form, arg_name, default, required, multiple, validate)
                return func(*args, **kwargs)
            return wrapper
        return decorator

    def from_header(self, param_name, param_type, default=None, required=False, multiple=False, validate=None, arg_name=None):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                self.__parse_into_param(kwargs, param_name, param_type, request.headers, arg_name, default, required, multiple, validate)
                return func(*args, **kwargs)
            return wrapper
        return decorator

    def from_query(self, param_name, param_type, default=None, required=False, multiple=False, validate=None, arg_name=None):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                self.__parse_into_param(kwargs, param_name, param_type, request.args, arg_name, default, required, multiple, validate)
                return func(*args, **kwargs)
            return wrapper
        return decorator

    def render(self):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                return self.__encode_into_body(func(*args, **kwargs))
            return wrapper
        return decorator

    def __decode_into_param(self, params, param_name, param_type, required, validate):
        data = request.get_data()

        if not data and required:
            raise ValidationError(ErrorReason.required_parameter, 'payload', 'Payload is missing.')

        try:
            if param_type is str:
                arg_value = data.decode()
            else:
                arg_value = self.__decode(data)
        except Exception as e:
            if isinstance(e, MediaTypeSupported):
                raise
            raise ValidationError(ErrorReason.invalid_parameter, 'payload', 'Payload is invalid.')

        if validate:
            try:
                success = validate(arg_value)
            except Exception as e:
                if isinstance(e, ValidationError):
                    raise
                success = False

            if not success:
                raise ValidationError(ErrorReason.invalid_parameter, 'payload', 'Payload is invalid.')

        params[param_name] = arg_value

    def __decode(self, data):
        content_type = request.headers['content-type']

        if content_type:
            media_type = content_type.split(';')[0]
        else:
            media_type = self.default_decoder

        decoder = self.__decoders.get(media_type)

        if not decoder:
            raise MediaTypeSupported([media_type], 'Media type not supported: %s' % media_type)

        return decoder(data)

    def __encode_into_body(self, data):
        status = headers = None
        if isinstance(data, tuple):
            data, status, headers = data + (None,) * (3 - len(data))

        if not isinstance(data, Response):
            media_type, data_bytes = self.__encode(data)
            data = Response(data_bytes, mimetype=media_type)

        if status is not None:
            if isinstance(status, str):
                data.status = status
            else:
                data.status_code = status

        if headers:
            data.headers.extend(headers)

        return data

    def __encode(self, data):
        accept = request.headers['accept']

        if not accept or '*/*' in accept:
            media_types = [self.default_encoder]
        else:
            media_types = accept.split(',')

        media_type = None
        encoder = None

        for mt in media_types:
            media_type = mt.split(';')[0]
            encoder = self.__encoders.get(media_type)
            if encoder:
                break

        if not encoder:
            raise MediaTypeSupported(media_types, 'Media types not supported: %s' % ', '.join(media_types))

        return media_type, encoder(data)

    def __parse_into_param(self, params, param_name, param_type, args, arg_name, default, required, multiple, validate):
        if not arg_name:
            arg_name = param_name

        parser = self.__parsers.get(param_type)

        if not parser:
            raise FlaskIOError('Parameter type \'%s\' does not have a parser.' % str(param_type))

        if multiple:
            arg_values = args.getlist(arg_name) or [None]
            param_values = []
            for arg_value in arg_values:
                param_values.append(self.__parse(parser, param_type, arg_name, arg_value, default, required, validate))
            params[param_name] = param_values
        else:
            arg_value = args.get(arg_name)
            params[param_name] = self.__parse(parser, param_type, arg_name, arg_value, default, required, validate)

    @staticmethod
    def __parse(parser, param_type, arg_name, arg_value, default, required, validate):
        try:
            if arg_value:
                arg_value = parser(param_type, arg_value)
        except:
            raise ValidationError(ErrorReason.invalid_parameter, arg_name, 'Argument \'%s\' is invalid.' % arg_name)

        if not arg_value:
            if required:
                raise ValidationError(ErrorReason.required_parameter, arg_name, 'Argument \'%s\' is missing.' % arg_name)

            if default:
                if callable(default):
                    arg_value = default()
                else:
                    arg_value = default

        if validate:
            try:
                success = validate(arg_name, arg_value)
            except Exception as e:
                if isinstance(e, ValidationError):
                    raise
                success = False

            if not success:
                raise ValidationError(ErrorReason.invalid_parameter, arg_name, 'Argument \'%s\' is invalid.' % arg_name)

        return arg_value