from braintree.exceptions.not_found_error import NotFoundError
from braintree.exceptions.unexpected_error import UnexpectedError

from django.db import models
from django.db.models.fields.related import RelatedField, RelatedObject
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.forms.models import model_to_dict
from django.utils.timezone import now


class BTSyncedModel(models.Model):
    """ A django model for 2-way sync with the braintree vault.
        Subclasses MUST define a collection variable.
    """

    # This is the vault data collection we sync with
    collection = None

    # Our timestamps, not to be confused the the braintree timestamps
    created = models.DateTimeField(editable=False, null=True)
    updated = models.DateTimeField(editable=False, null=True)

    # Timestamp are never synced
    always_exclude = ('created', 'updated')

    class Meta:
        get_latest_by = "created"
        abstract = True

    def braintree_key(self):
        """ A represantion of how this instance is indexed in the vault """
        raise NotImplementedError('braintree_key() not implemented')

    def serialize(self, exclude=()):
        """ The shared serialization method """
        data = model_to_dict(self, exclude=self.always_exclude + exclude)
        for key in data.keys():
            value = data[key]
            if value:
                data[key] = unicode(value)
            else:
                del data[key]
        return data

    def serialize_create(self):
        """ When a instance is to be create in the vault """
        return self.serialize()

    def serialize_update(self):
        """ When a instance is to be updated in the vault """
        return self.serialize()

    def on_pushed(self, result):
        """ This is called after a object was pushed into the vault """
        pass

    @classmethod
    def unserialize(cls, data):
        """ Should create a unsaved django object from a vault object """
        pass

    def push(self):
        """ Push this instance into the vault """
        key = self.braintree_key()

        try:
            data = self.serialize_update()
            result = self.collection.update(*key, params=data)
        except (NotFoundError, KeyError, UnexpectedError):
            data = self.serialize_create()
            result = self.collection.create(data)
            self.created = now()

        if not result.is_success:
            raise ValidationError(result.message)
        else:
            self.on_pushed(result)
            self.updated = now()

    def push_related(self):
        """ Implement this to automatically push related BTSyncedModels """
        pass

    def pull_related(self):
        """ Implement this to pull BTMirroredModels from braintree """
        pass

    def pull(self):
        """ Pull and sync data from vault into local instance """
        key = self.braintree_key()
        data = self.collection.find(*key)
        self.import_data(data)

    def import_data(self, data):
        """ Save the data from the vault onto the instance """
        for key, value in data.__dict__.iteritems():
            if hasattr(self, key) and key != 'id':
                field = self._meta.get_field_by_name(key)[0]
                if not issubclass(field.__class__, RelatedObject):
                    setattr(self, key, value)
        self.updated = now()
        self.save()

    """ Deprecated: implement this independentantly from import
    def import_related(self, related_model, data):
        for object in data:
            try:
                other = related_model.objects.get(pk=object.id)
                other.import_data(object)
            except ObjectDoesNotExist:
                new = related_model.unserialize(object)
                if new is not None:
                    new.save()
    """

    def delete_from_vault(self):
        """ Remove object from vault """
        if hasattr(self.collection, 'delete'):
            try:
                self.collection.delete(*self.braintree_key())
            except (NotFoundError, KeyError):
                pass


class BTMirroredModel(models.Model):
    """ A django model that only updates itself from the vault.
        Subclasses MUST define a collection variable.
    """

    # This is the vault data collection we mirror from
    collection = None

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super(BTMirroredModel, self).__init__(*args, **kwargs)

        # data is the last received representation from braintree
        # when get_data_from_vault() is called
        self.data = None

    def braintree_key(self):
        """ A represantion of how this instance is indexed in the vault """
        raise NotImplementedError('braintree_key() not implemented')

    def reset_fields(self):
        """ empty all cached fields from the model """
        for field in self._meta.fields:
            is_editable = getattr(field, 'editable', True)
            is_nullable = getattr(field, 'null', False)
            if is_nullable and not is_editable:
                setattr(self, field.name, None)

    def get_data_from_vault(self):
        """ Get object data from vault """
        key = self.braintree_key()
        if hasattr(self.collection, 'find'):
            try:
                self.data = self.collection.find(*key)
            except (NotFoundError, KeyError):
                pass
        else:
            find_by_id = lambda obj: obj.id == key[0]
            found = filter(find_by_id, self.collection.all())
            self.data = found[0] if found else None

        return self.data

    def import_data(self, data):
        """ How the data from the vault into the instance """
        raise NotImplementedError('import_data(data) not implemented')

    def import_related(self, data):
        """ import related objects from vault """
        raise NotImplementedError('import_releated(data) not implemented')

    def pull(self):
        self.get_data_from_vault()
        if self.data:
            self.import_data(self.data)
        else:
            self.reset_fields()

    def pull_related(self):
        if not self.data:
            self.get_data_from_vault()

        for field_name in self._meta.get_all_field_names():
            field = self._meta.get_field_by_name(field_name)[0]
            if issubclass(field.__class__, RelatedObject):
                related_objects = getattr(self.data, field_name, ())
                field.model.import_related(self, related_objects)

    def delete_from_vault(self):
        """ Remove object from vault if present """
        if hasattr(self.collection, 'delete'):
            try:
                self.collection.delete(*self.braintree_key())
            except (NotFoundError, KeyError):
                pass
