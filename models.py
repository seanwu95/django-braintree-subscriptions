import braintree

from django.db import models
from django.db.models.fields.related import RelatedObject

from .sync import BraintreeSyncedModel, BraintreeMirroredModel


# Common attributes for cached fields
CACHED = {'editable': False, 'blank': True, 'null': True}


class Customer(BraintreeSyncedModel(braintree.Customer)):
    id = models.OneToOneField('customers.Customer',
        related_name='braintree', primary_key=True)

    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    fax = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=255, blank=True, null=True)
    website = models.URLField(verify_exists=False, blank=True, null=True)

    def __unicode__(self):
        return self.full_name

    def braintree_key(self):
        return (str(self.id.pk),)

    @property
    def full_name(self):
        return u'%s %s' % (self.first_name, self.last_name)


class Address(BraintreeSyncedModel(braintree.Address)):
    code = models.CharField(max_length=100, unique=True)
    customer = models.ForeignKey(Customer, related_name='addresses')

    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    street_address = models.CharField(max_length=255, blank=True, null=True)
    extended_address = models.CharField(max_length=255, blank=True, null=True)
    locality = models.CharField(max_length=255, blank=True, null=True)
    region = models.CharField(max_length=255, blank=True, null=True)
    postal_code = models.CharField(max_length=255, blank=True, null=True)
    country_code_alpha2 = models.CharField(max_length=255, blank=True, null=True)

    serialize_exclude = ('id',)

    def __unicode__(self):
        return self.code

    def braintree_key(self):
        return (str(self.customer.pk), self.code or '0')

    def serialize_create(self):
        data = self.serialize(exclude=('id', 'code', 'customer'))
        data['customer_id'] = str(self.customer.pk)
        return data

    def serialize_update(self):
        return self.serialize(exclude=('id', 'code', 'customer'))

    @classmethod
    def unserialize(cls, data):
        address = Address()
        for key, value in data.__dict__.iteritems():
            if hasattr(address, key):
                setattr(address, key, value)
        address.customer_id = int(data.customer_id)
        return address

    def on_pushed(self, result):
        if not self.code == result.address.id:
            self.code = result.address.id


class CreditCard(BraintreeMirroredModel(braintree.CreditCard)):
    token = models.CharField(max_length=100, unique=True)
    customer = models.ForeignKey(Customer, related_name='credit_cards')

    default = models.NullBooleanField(**CACHED)

    bin = models.IntegerField(**CACHED)
    last_4 = models.IntegerField(**CACHED)
    cardholder_name = models.CharField(max_length=255, **CACHED)
    expiration_month = models.IntegerField(**CACHED)
    expiration_year = models.IntegerField(**CACHED)
    expiration_date = models.CharField(max_length=255, **CACHED)
    masked_number = models.CharField(max_length=255, **CACHED)
    unique_number_identifier = models.CharField(max_length=255, **CACHED)

    country_of_issuance = models.CharField(max_length=255, **CACHED)
    issuing_bank = models.CharField(max_length=255, **CACHED)

    # There are more boolean fields in braintree available, yet i don't think
    # We need them for now

    def __unicode__(self):
        return self.mask

    @property
    def mask(self):
        if self.masked_number:
            return self.masked_number
        elif self.bin and self.last_4:
            return '%s******%s' % (self.bin, self.last_4)
        else:
            return self.token

    def braintree_key(self):
        return (self.token or '0',)

    def import_data(self, data):
        for key, value in data.__dict__.iteritems():
            if hasattr(self, key):
                setattr(self, key, value)
        self.customer_id = int(data.customer_id)


class Plan(BraintreeMirroredModel(braintree.Plan)):
    plan_id = models.CharField(max_length=100, unique=True)

    name = models.CharField(max_length=100, **CACHED)
    description = models.TextField(**CACHED)
    price = models.DecimalField(max_digits=5, decimal_places=2, **CACHED)
    currency_iso_code = models.CharField(max_length=100, **CACHED)

    billing_day_of_month = models.IntegerField(**CACHED)
    billing_frequency = models.IntegerField(help_text='in months', **CACHED)
    number_of_billing_cycles = models.IntegerField(**CACHED)

    trial_period = models.NullBooleanField(**CACHED)
    trial_duration = models.IntegerField(**CACHED)
    trial_duration_unit = models.CharField(max_length=100, **CACHED)

    # Timestamp from braintree
    created_at = models.DateTimeField(**CACHED)
    updated_at = models.DateTimeField(**CACHED)

    def __unicode__(self):
        return self.name if self.name else self.plan_id

    def braintree_key(self):
        return (self.plan_id,)

    def import_data(self, data):
        for key, value in data.__dict__.iteritems():
            if hasattr(self, key) and key != 'id':
                field = self._meta.get_field_by_name(key)[0]
                if not issubclass(field.__class__, RelatedObject):
                    setattr(self, key, value)

    # Addons and Discounts
    def import_related(self, data):
        for key, value in data.__dict__.iteritems():
            if hasattr(self, key) and key != 'id':
                field = self._meta.get_field_by_name(key)[0]
                if issubclass(field.__class__, RelatedObject):
                    field.model.import_related(self, value)

    @property
    def price_display(self):
        return u'%s %s', (self.price, self.currency_iso_code)


class AddOn(models.Model):
    plan = models.ForeignKey(Plan, related_name='add_ons')
    addon_id = models.CharField(max_length=255, unique=True, **CACHED)

    name = models.CharField(max_length=255, **CACHED)
    description = models.TextField(**CACHED)
    amount = models.DecimalField(max_digits=5, decimal_places=2, **CACHED)
    number_of_billing_cycles = models.IntegerField(**CACHED)

    mark_for_delete = models.BooleanField(editable=False)

    def __unicode__(self):
        return self.name if self.name else self.addon_id

    @classmethod
    def import_related(cls, plan, addons):
        plan.add_ons.update(mark_for_delete=True)

        for addon in addons:
            try:
                instance = AddOn.objects.get(plan=plan, addon_id=addon.id)
            except AddOn.DoesNotExist:
                instance = AddOn(plan=plan, addon_id=addon.id)

            instance.mark_for_delete = False
            for key, value in addon.__dict__.iteritems():
                if hasattr(instance, key) and key != 'id':
                    setattr(instance, key, value)
            instance.save()

        plan.add_ons.filter(mark_for_delete=True).delete()


class Discount(models.Model):
    plan = models.ForeignKey(Plan, related_name='discounts')
    discount_id = models.CharField(max_length=255, unique=True, **CACHED)

    name = models.CharField(max_length=255, **CACHED)
    description = models.TextField(**CACHED)
    amount = models.DecimalField(max_digits=5, decimal_places=2, **CACHED)
    number_of_billing_cycles = models.IntegerField(**CACHED)

    mark_for_delete = models.BooleanField(editable=False)

    def __unicode__(self):
        return self.name if self.name else self.discount_id

    @classmethod
    def import_related(cls, plan, discounts):
        plan.discounts.update(mark_for_delete=True)

        for discount in discounts:
            try:
                instance = Discount.objects.get(
                    plan=plan,
                    discount_id=discount.id
                )
            except Discount.DoesNotExist:
                instance = Discount(plan=plan, discount_id=discount.id)

            instance.mark_for_delete = False
            for key, value in discount.__dict__.iteritems():
                if hasattr(instance, key) and key != 'id':
                    setattr(instance, key, value)
            instance.save()

        plan.add_ons.filter(mark_for_delete=True).delete()
