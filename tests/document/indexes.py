# -*- coding: utf-8 -*-
from __future__ import with_statement
import bson
import os
import pickle
import pymongo
import sys
import unittest
import uuid
import warnings

from nose.plugins.skip import SkipTest
from datetime import datetime

from tests.fixtures import Base, Mixin, PickleEmbedded, PickleTest

from mongoengine import *
from mongoengine.errors import (NotRegistered, InvalidDocumentError,
                                InvalidQueryError)
from mongoengine.queryset import NULLIFY, Q
from mongoengine.connection import get_db, get_connection

TEST_IMAGE_PATH = os.path.join(os.path.dirname(__file__), 'mongoengine.png')

__all__ = ("InstanceTest", )


class InstanceTest(unittest.TestCase):

    def setUp(self):
        connect(db='mongoenginetest')
        self.db = get_db()

        class Person(Document):
            name = StringField()
            age = IntField()

            non_field = True

            meta = {"allow_inheritance": True}

        self.Person = Person

    def tearDown(self):
        for collection in self.db.collection_names():
            if 'system.' in collection:
                continue
            self.db.drop_collection(collection)

    def test_indexes_document(self, ):
        """Ensure that indexes are used when meta[indexes] is specified for
        Documents
        """
        index_test(Document)

    def test_indexes_dynamic_document(self, ):
        """Ensure that indexes are used when meta[indexes] is specified for
        Dynamic Documents
        """
        index_test(DynamicDocument)

    def index_test(self, InheritFrom):

        class BlogPost(InheritFrom):
            date = DateTimeField(db_field='addDate', default=datetime.now)
            category = StringField()
            tags = ListField(StringField())
            meta = {
                'indexes': [
                    '-date',
                    'tags',
                    ('category', '-date')
                ],
                'allow_inheritance': True
            }

        expected_specs = [{'fields': [('_cls', 1), ('addDate', -1)]},
                          {'fields': [('_cls', 1), ('tags', 1)]},
                          {'fields': [('_cls', 1), ('category', 1),
                                      ('addDate', -1)]}]
        self.assertEqual(expected_specs, BlogPost._meta['index_specs'])

        BlogPost.ensure_indexes()
        info = BlogPost.objects._collection.index_information()
        # _id, '-date', 'tags', ('cat', 'date')
        # NB: there is no index on _cls by itself, since
        # the indices on -date and tags will both contain
        # _cls as first element in the key
        self.assertEqual(len(info), 4)
        info = [value['key'] for key, value in info.iteritems()]
        for expected in expected_specs:
            self.assertTrue(expected['fields'] in info)

        class ExtendedBlogPost(BlogPost):
            title = StringField()
            meta = {'indexes': ['title']}

        expected_specs.append({'fields': [('_cls', 1), ('title', 1)]})
        self.assertEqual(expected_specs, ExtendedBlogPost._meta['index_specs'])

        BlogPost.drop_collection()

        ExtendedBlogPost.ensure_indexes()
        info = ExtendedBlogPost.objects._collection.index_information()
        info = [value['key'] for key, value in info.iteritems()]
        for expected in expected_specs:
            self.assertTrue(expected['fields'] in info)

    def test_inherited_index(self):
        """Ensure index specs are inhertited correctly"""

        class A(Document):
            title = StringField()
            meta = {
                'indexes': [
                        {
                        'fields': ('title',),
                        },
                ],
                'allow_inheritance': True,
                }

        class B(A):
            description = StringField()

        self.assertEqual(A._meta['index_specs'], B._meta['index_specs'])
        self.assertEqual([{'fields': [('_cls', 1), ('title', 1)]}],
                         A._meta['index_specs'])

    def test_build_index_spec_is_not_destructive(self):

        class MyDoc(Document):
            keywords = StringField()

            meta = {
                'indexes': ['keywords'],
                'allow_inheritance': False
            }

        self.assertEqual(MyDoc._meta['index_specs'],
                         [{'fields': [('keywords', 1)]}])

        # Force index creation
        MyDoc.ensure_indexes()

        self.assertEqual(MyDoc._meta['index_specs'],
                        [{'fields': [('keywords', 1)]}])

    def test_embedded_document_index_meta(self):
        """Ensure that embedded document indexes are created explicitly
        """
        class Rank(EmbeddedDocument):
            title = StringField(required=True)

        class Person(Document):
            name = StringField(required=True)
            rank = EmbeddedDocumentField(Rank, required=False)

            meta = {
                'indexes': [
                    'rank.title',
                ],
                'allow_inheritance': False
            }

        self.assertEqual([{'fields': [('rank.title', 1)]}],
                        Person._meta['index_specs'])

        Person.drop_collection()

        # Indexes are lazy so use list() to perform query
        list(Person.objects)
        info = Person.objects._collection.index_information()
        info = [value['key'] for key, value in info.iteritems()]
        self.assertTrue([('rank.title', 1)] in info)

    def test_explicit_geo2d_index(self):
        """Ensure that geo2d indexes work when created via meta[indexes]
        """
        class Place(Document):
            location = DictField()
            meta = {
                'allow_inheritance': True,
                'indexes': [
                    '*location.point',
                ]
            }

        self.assertEqual([{'fields': [('location.point', '2d')]}],
                        Place._meta['index_specs'])

        Place.ensure_indexes()
        info = Place._get_collection().index_information()
        info = [value['key'] for key, value in info.iteritems()]
        self.assertTrue([('location.point', '2d')] in info)

    def test_dictionary_indexes(self):
        """Ensure that indexes are used when meta[indexes] contains
        dictionaries instead of lists.
        """
        class BlogPost(Document):
            date = DateTimeField(db_field='addDate', default=datetime.now)
            category = StringField()
            tags = ListField(StringField())
            meta = {
                'indexes': [
                    {'fields': ['-date'], 'unique': True,
                      'sparse': True, 'types': False},
                ],
            }

        self.assertEqual([{'fields': [('addDate', -1)], 'unique': True,
                          'sparse': True, 'types': False}],
                        BlogPost._meta['index_specs'])

        BlogPost.drop_collection()

        info = BlogPost.objects._collection.index_information()
        # _id, '-date'
        self.assertEqual(len(info), 3)

        # Indexes are lazy so use list() to perform query
        list(BlogPost.objects)
        info = BlogPost.objects._collection.index_information()
        info = [(value['key'],
                 value.get('unique', False),
                 value.get('sparse', False))
                for key, value in info.iteritems()]
        self.assertTrue(([('addDate', -1)], True, True) in info)

        BlogPost.drop_collection()

    def test_abstract_index_inheritance(self):

        class UserBase(Document):
            user_guid = StringField(required=True)
            meta = {
                'abstract': True,
                'indexes': ['user_guid'],
                'allow_inheritance': True
            }

        class Person(UserBase):
            name = StringField()

            meta = {
                'indexes': ['name'],
            }

        Person(name="test", user_guid='123').save()

        self.assertEqual(1, Person.objects.count())
        info = Person.objects._collection.index_information()
        self.assertEqual(info.keys(), ['_cls_1_name_1', '_cls_1_user_guid_1',
                                       '_id_'])

    def test_disable_index_creation(self):
        """Tests setting auto_create_index to False on the connection will
        disable any index generation.
        """
        class User(Document):
            meta = {
                'indexes': ['user_guid'],
                'auto_create_index': False
            }
            user_guid = StringField(required=True)


        User.drop_collection()

        u = User(user_guid='123')
        u.save()

        self.assertEqual(1, User.objects.count())
        info = User.objects._collection.index_information()
        self.assertEqual(info.keys(), ['_id_'])
        User.drop_collection()

    def test_embedded_document_index(self):
        """Tests settings an index on an embedded document
        """
        class Date(EmbeddedDocument):
            year = IntField(db_field='yr')

        class BlogPost(Document):
            title = StringField()
            date = EmbeddedDocumentField(Date)

            meta = {
                'indexes': [
                    '-date.year'
                ],
            }

        BlogPost.drop_collection()

        info = BlogPost.objects._collection.index_information()
        self.assertEqual(info.keys(), ['_cls_1_date.yr_-1', '_id_'])
        BlogPost.drop_collection()

    def test_list_embedded_document_index(self):
        """Ensure list embedded documents can be indexed
        """
        class Tag(EmbeddedDocument):
            name = StringField(db_field='tag')

        class BlogPost(Document):
            title = StringField()
            tags = ListField(EmbeddedDocumentField(Tag))

            meta = {
                'indexes': [
                    'tags.name'
                ]
            }

        BlogPost.drop_collection()

        info = BlogPost.objects._collection.index_information()
        # we don't use _cls in with list fields by default
        self.assertEqual(info.keys(), ['_id_', '_cls_1_tags.tag_1'])

        post1 = BlogPost(title="Embedded Indexes tests in place",
                        tags=[Tag(name="about"), Tag(name="time")]
                )
        post1.save()
        BlogPost.drop_collection()

    def test_recursive_embedded_objects_dont_break_indexes(self):

        class RecursiveObject(EmbeddedDocument):
            obj = EmbeddedDocumentField('self')

        class RecursiveDocument(Document):
            recursive_obj = EmbeddedDocumentField(RecursiveObject)
            meta = {'allow_inheritance': True}

        RecursiveDocument.ensure_indexes()
        info = RecursiveDocument._get_collection().index_information()
        self.assertEqual(info.keys(), ['_id_', '_cls_1'])

    def test_geo_indexes_recursion(self):

        class Location(Document):
            name = StringField()
            location = GeoPointField()

        class Parent(Document):
            name = StringField()
            location = ReferenceField(Location)

        Location.drop_collection()
        Parent.drop_collection()

        list(Parent.objects)

        collection = Parent._get_collection()
        info = collection.index_information()

        self.assertFalse('location_2d' in info)

        self.assertEqual(len(Parent._geo_indices()), 0)
        self.assertEqual(len(Location._geo_indices()), 1)

    def test_covered_index(self):
        """Ensure that covered indexes can be used
        """

        class Test(Document):
            a = IntField()

            meta = {
                'indexes': ['a'],
                'allow_inheritance': False
                }

        Test.drop_collection()

        obj = Test(a=1)
        obj.save()

        # Need to be explicit about covered indexes as mongoDB doesn't know if
        # the documents returned might have more keys in that here.
        query_plan = Test.objects(id=obj.id).exclude('a').explain()
        self.assertFalse(query_plan['indexOnly'])

        query_plan = Test.objects(id=obj.id).only('id').explain()
        self.assertTrue(query_plan['indexOnly'])

        query_plan = Test.objects(a=1).only('a').exclude('id').explain()
        self.assertTrue(query_plan['indexOnly'])

    def test_index_on_id(self):

        class BlogPost(Document):
            meta = {
                'indexes': [
                    ['categories', 'id']
                ],
                'allow_inheritance': False
            }

            title = StringField(required=True)
            description = StringField(required=True)
            categories = ListField()

        BlogPost.drop_collection()

        indexes = BlogPost.objects._collection.index_information()
        self.assertEqual(indexes['categories_1__id_1']['key'],
                                 [('categories', 1), ('_id', 1)])

    def test_hint(self):

        class BlogPost(Document):
            tags = ListField(StringField())
            meta = {
                'indexes': [
                    'tags',
                ],
            }

        BlogPost.drop_collection()

        for i in xrange(0, 10):
            tags = [("tag %i" % n) for n in xrange(0, i % 2)]
            BlogPost(tags=tags).save()

        self.assertEqual(BlogPost.objects.count(), 10)
        self.assertEqual(BlogPost.objects.hint().count(), 10)
        self.assertEqual(BlogPost.objects.hint([('tags', 1)]).count(), 10)

        self.assertEqual(BlogPost.objects.hint([('ZZ', 1)]).count(), 10)

        def invalid_index():
            BlogPost.objects.hint('tags')
        self.assertRaises(TypeError, invalid_index)

        def invalid_index_2():
            return BlogPost.objects.hint(('tags', 1))
        self.assertRaises(TypeError, invalid_index_2)

    def test_unique(self):
        """Ensure that uniqueness constraints are applied to fields.
        """
        class BlogPost(Document):
            title = StringField()
            slug = StringField(unique=True)

        BlogPost.drop_collection()

        post1 = BlogPost(title='test1', slug='test')
        post1.save()

        # Two posts with the same slug is not allowed
        post2 = BlogPost(title='test2', slug='test')
        self.assertRaises(NotUniqueError, post2.save)

        # Ensure backwards compatibilty for errors
        self.assertRaises(OperationError, post2.save)

    def test_unique_with(self):
        """Ensure that unique_with constraints are applied to fields.
        """
        class Date(EmbeddedDocument):
            year = IntField(db_field='yr')

        class BlogPost(Document):
            title = StringField()
            date = EmbeddedDocumentField(Date)
            slug = StringField(unique_with='date.year')

        BlogPost.drop_collection()

        post1 = BlogPost(title='test1', date=Date(year=2009), slug='test')
        post1.save()

        # day is different so won't raise exception
        post2 = BlogPost(title='test2', date=Date(year=2010), slug='test')
        post2.save()

        # Now there will be two docs with the same slug and the same day: fail
        post3 = BlogPost(title='test3', date=Date(year=2010), slug='test')
        self.assertRaises(OperationError, post3.save)

        BlogPost.drop_collection()

    def test_unique_embedded_document(self):
        """Ensure that uniqueness constraints are applied to fields on embedded documents.
        """
        class SubDocument(EmbeddedDocument):
            year = IntField(db_field='yr')
            slug = StringField(unique=True)

        class BlogPost(Document):
            title = StringField()
            sub = EmbeddedDocumentField(SubDocument)

        BlogPost.drop_collection()

        post1 = BlogPost(title='test1', sub=SubDocument(year=2009, slug="test"))
        post1.save()

        # sub.slug is different so won't raise exception
        post2 = BlogPost(title='test2', sub=SubDocument(year=2010, slug='another-slug'))
        post2.save()

        # Now there will be two docs with the same sub.slug
        post3 = BlogPost(title='test3', sub=SubDocument(year=2010, slug='test'))
        self.assertRaises(NotUniqueError, post3.save)

        BlogPost.drop_collection()

    def test_unique_with_embedded_document_and_embedded_unique(self):
        """Ensure that uniqueness constraints are applied to fields on
        embedded documents.  And work with unique_with as well.
        """
        class SubDocument(EmbeddedDocument):
            year = IntField(db_field='yr')
            slug = StringField(unique=True)

        class BlogPost(Document):
            title = StringField(unique_with='sub.year')
            sub = EmbeddedDocumentField(SubDocument)

        BlogPost.drop_collection()

        post1 = BlogPost(title='test1', sub=SubDocument(year=2009, slug="test"))
        post1.save()

        # sub.slug is different so won't raise exception
        post2 = BlogPost(title='test2', sub=SubDocument(year=2010, slug='another-slug'))
        post2.save()

        # Now there will be two docs with the same sub.slug
        post3 = BlogPost(title='test3', sub=SubDocument(year=2010, slug='test'))
        self.assertRaises(NotUniqueError, post3.save)

        # Now there will be two docs with the same title and year
        post3 = BlogPost(title='test1', sub=SubDocument(year=2009, slug='test-1'))
        self.assertRaises(NotUniqueError, post3.save)

        BlogPost.drop_collection()

    def test_ttl_indexes(self):

        class Log(Document):
            created = DateTimeField(default=datetime.now)
            meta = {
                'indexes': [
                    {'fields': ['created'], 'expireAfterSeconds': 3600}
                ]
            }

        Log.drop_collection()

        if pymongo.version_tuple[0] < 2 and pymongo.version_tuple[1] < 3:
            raise SkipTest('pymongo needs to be 2.3 or higher for this test')

        connection = get_connection()
        version_array = connection.server_info()['versionArray']
        if version_array[0] < 2 and version_array[1] < 2:
            raise SkipTest('MongoDB needs to be 2.2 or higher for this test')

        # Indexes are lazy so use list() to perform query
        list(Log.objects)
        info = Log.objects._collection.index_information()
        self.assertEqual(3600,
                info['_cls_1_created_1']['expireAfterSeconds'])

    def test_unique_and_indexes(self):
        """Ensure that 'unique' constraints aren't overridden by
        meta.indexes.
        """
        class Customer(Document):
            cust_id = IntField(unique=True, required=True)
            meta = {
                'indexes': ['cust_id'],
                'allow_inheritance': False,
            }

        Customer.drop_collection()
        cust = Customer(cust_id=1)
        cust.save()

        cust_dupe = Customer(cust_id=1)
        try:
            cust_dupe.save()
            raise AssertionError, "We saved a dupe!"
        except NotUniqueError:
            pass
        Customer.drop_collection()

    def test_unique_and_primary(self):
        """If you set a field as primary, then unexpected behaviour can occur.
        You won't create a duplicate but you will update an existing document.
        """

        class User(Document):
            name = StringField(primary_key=True, unique=True)
            password = StringField()

        User.drop_collection()

        user = User(name='huangz', password='secret')
        user.save()

        user = User(name='huangz', password='secret2')
        user.save()

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get().password, 'secret2')

        User.drop_collection()

    def test_types_index_with_pk(self):
        """Ensure you can use `pk` as part of a query"""

        class Comment(EmbeddedDocument):
            comment_id = IntField(required=True)

        try:
            class BlogPost(Document):
                comments = EmbeddedDocumentField(Comment)
                meta = {'indexes': [
                            {'fields': ['pk', 'comments.comment_id'],
                             'unique': True}]}
        except UnboundLocalError:
            self.fail('Unbound local error at types index + pk definition')

        info = BlogPost.objects._collection.index_information()
        info = [value['key'] for key, value in info.iteritems()]
        index_item = [('_cls', 1), ('_id', 1), ('comments.comment_id', 1)]
        self.assertTrue(index_item in info)

if __name__ == '__main__':
    unittest.main()