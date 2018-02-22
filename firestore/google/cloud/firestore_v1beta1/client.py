# Copyright 2017 Google LLC All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Client for interacting with the Google Cloud Firestore API.

This is the base from which all interactions with the API occur.

In the hierarchy of API concepts

* a :class:`~.firestore_v1beta1.client.Client` owns a
  :class:`~.firestore_v1beta1.collection.CollectionReference`
* a :class:`~.firestore_v1beta1.client.Client` owns a
  :class:`~.firestore_v1beta1.document.DocumentReference`
"""

from google.cloud._helpers import make_secure_channel
from google.cloud._http import DEFAULT_USER_AGENT
from google.cloud.client import ClientWithProject

from google.cloud.firestore_v1beta1 import __version__
from google.cloud.firestore_v1beta1 import _helpers
from google.cloud.firestore_v1beta1 import types
from google.cloud.firestore_v1beta1.batch import WriteBatch
from google.cloud.firestore_v1beta1.collection import CollectionReference
from google.cloud.firestore_v1beta1.document import DocumentReference
from google.cloud.firestore_v1beta1.document import DocumentSnapshot
from google.cloud.firestore_v1beta1.gapic import firestore_client
from google.cloud.firestore_v1beta1.transaction import Transaction


DEFAULT_DATABASE = '(default)'
"""str: The default database used in a :class:`~.firestore.client.Client`."""
_BAD_OPTION_ERR = (
    'Exactly one of ``create_if_missing``, ``last_update_time`` '
    'and ``exists`` must be provided.')
_BAD_DOC_TEMPLATE = (
    'Document {!r} appeared in response but was not present among references')
_ACTIVE_TXN = 'There is already an active transaction.'
_INACTIVE_TXN = 'There is no active transaction.'


class Client(ClientWithProject):
    """Client for interacting with Google Cloud Firestore API.

    .. note::

        Since the Cloud Firestore API requires the gRPC transport, no
        ``_http`` argument is accepted by this class.

    Args:
        project (Optional[str]): The project which the client acts on behalf
            of. If not passed, falls back to the default inferred
            from the environment.
        credentials (Optional[~google.auth.credentials.Credentials]): The
            OAuth2 Credentials to use for this client. If not passed, falls
            back to the default inferred from the environment.
        database (Optional[str]): The database name that the client targets.
            For now, :attr:`DEFAULT_DATABASE` (the default value) is the
            only valid database.
    """

    SCOPE = (
        'https://www.googleapis.com/auth/cloud-platform',
        'https://www.googleapis.com/auth/datastore',
    )
    """The scopes required for authenticating with the Firestore service."""

    _firestore_api_internal = None
    _database_string_internal = None
    _rpc_metadata_internal = None

    def __init__(self, project=None, credentials=None,
                 database=DEFAULT_DATABASE):
        # NOTE: This API has no use for the _http argument, but sending it
        #       will have no impact since the _http() @property only lazily
        #       creates a working HTTP object.
        super(Client, self).__init__(
            project=project, credentials=credentials, _http=None)
        self._database = database

    @property
    def _firestore_api(self):
        """Lazy-loading getter GAPIC Firestore API.

        Returns:
            ~.gapic.firestore.v1beta1.firestore_client.FirestoreClient: The
            GAPIC client with the credentials of the current client.
        """
        if self._firestore_api_internal is None:
            self._firestore_api_internal = _make_firestore_api(self)

        return self._firestore_api_internal

    @property
    def _database_string(self):
        """The database string corresponding to this client's project.

        This value is lazy-loaded and cached.

        Will be of the form

            ``projects/{project_id}/databases/{database_id}``

        but ``database_id == '(default)'`` for the time being.

        Returns:
            str: The fully-qualified database string for the current
            project. (The default database is also in this string.)
        """
        if self._database_string_internal is None:
            # NOTE: database_root_path() is a classmethod, so we don't use
            #       self._firestore_api (it isn't necessary).
            db_str = firestore_client.FirestoreClient.database_root_path(
                self.project, self._database)
            self._database_string_internal = db_str

        return self._database_string_internal

    @property
    def _rpc_metadata(self):
        """The RPC metadata for this client's associated database.

        Returns:
            Sequence[Tuple(str, str)]: RPC metadata with resource prefix
            for the database associated with this client.
        """
        if self._rpc_metadata_internal is None:
            self._rpc_metadata_internal = _helpers.metadata_with_prefix(
                self._database_string)

        return self._rpc_metadata_internal

    def collection(self, *collection_path):
        """Get a reference to a collection.

        For a top-level collection:

        .. code-block:: python

            >>> client.collection('top')

        For a sub-collection:

        .. code-block:: python

            >>> client.collection('mydocs/doc/subcol')
            >>> # is the same as
            >>> client.collection('mydocs', 'doc', 'subcol')

        Sub-collections can be nested deeper in a similar fashion.

        Args:
            collection_path (Tuple[str, ...]): Can either be

                * A single ``/``-delimited path to a collection
                * A tuple of collection path segments

        Returns:
            ~.firestore_v1beta1.collection.CollectionReference: A reference
            to a collection in the Firestore database.
        """
        if len(collection_path) == 1:
            path = collection_path[0].split(_helpers.DOCUMENT_PATH_DELIMITER)
        else:
            path = collection_path

        return CollectionReference(*path, client=self)

    def document(self, *document_path):
        """Get a reference to a document in a collection.

        For a top-level document:

        .. code-block:: python

            >>> client.document('collek/shun')
            >>> # is the same as
            >>> client.document('collek', 'shun')

        For a document in a sub-collection:

        .. code-block:: python

            >>> client.document('mydocs/doc/subcol/child')
            >>> # is the same as
            >>> client.document('mydocs', 'doc', 'subcol', 'child')

        Documents in sub-collections can be nested deeper in a similar fashion.

        Args:
            document_path (Tuple[str, ...]): Can either be

                * A single ``/``-delimited path to a document
                * A tuple of document path segments

        Returns:
            ~.firestore_v1beta1.document.DocumentReference: A reference
            to a document in a collection.
        """
        if len(document_path) == 1:
            path = document_path[0].split(_helpers.DOCUMENT_PATH_DELIMITER)
        else:
            path = document_path

        return DocumentReference(*path, client=self)

    @staticmethod
    def field_path(*field_names):
        """Create a **field path** from a list of nested field names.

        A **field path** is a ``.``-delimited concatenation of the field
        names. It is used to represent a nested field. For example,
        in the data

        .. code-block:: python

           data = {
              'aa': {
                  'bb': {
                      'cc': 10,
                  },
              },
           }

        the field path ``'aa.bb.cc'`` represents the data stored in
        ``data['aa']['bb']['cc']``.

        Args:
            field_names (Tuple[str, ...]): The list of field names.

        Returns:
            str: The ``.``-delimited field path.
        """
        return _helpers.get_field_path(field_names)

    @staticmethod
    def write_option(**kwargs):
        """Create a write option for write operations.

        Write operations include :meth:`~.DocumentReference.set`,
        :meth:`~.DocumentReference.update` and
        :meth:`~.DocumentReference.delete`.

        Exactly one of three keyword arguments must be provided:

        * ``create_if_missing`` (:class:`bool`): Indicates if the document
          should be created if it doesn't already exist.
        * ``last_update_time`` (:class:`google.protobuf.timestamp_pb2.\
           Timestamp`): A timestamp. When set, the target document must exist
           and have been last updated at that time. Protobuf ``update_time``
           timestamps are typically returned from methods that perform write
           operations as part of a "write result" protobuf or directly.
        * ``exists`` (:class:`bool`): Indicates if the document being modified
          should already exist.

        Providing no argument would make the option have no effect (so
        it is not allowed). Providing multiple would be an apparent
        contradiction, since ``last_update_time`` assumes that the
        document **was** updated (it can't have been updated if it
        doesn't exist) and both ``create_if_missing`` and ``exists`` indicate
        that it is unknown if the document exists or not (but in different
        ways).

        Args:
            kwargs (Dict[str, Any]): The keyword arguments described above.

        Raises:
            TypeError: If anything other than exactly one argument is
                provided by the caller.
        """
        if len(kwargs) != 1:
            raise TypeError(_BAD_OPTION_ERR)

        name, value = kwargs.popitem()
        if name == 'create_if_missing':
            return CreateIfMissingOption(value)
        elif name == 'last_update_time':
            return LastUpdateOption(value)
        elif name == 'exists':
            return ExistsOption(value)
        else:
            extra = '{!r} was provided'.format(name)
            raise TypeError(_BAD_OPTION_ERR, extra)

    def get_all(self, references, field_paths=None, transaction=None):
        """Retrieve a batch of documents.

        .. note::

           Documents returned by this method are not guaranteed to be
           returned in the same order that they are given in ``references``.

        .. note::

           If multiple ``references`` refer to the same document, the server
           will only return one result.

        See :meth:`~.firestore_v1beta1.client.Client.field_path` for
        more information on **field paths**.

        If a ``transaction`` is used and it already has write operations
        added, this method cannot be used (i.e. read-after-write is not
        allowed).

        Args:
            references (List[.DocumentReference, ...]): Iterable of document
                references to be retrieved.
            field_paths (Optional[Iterable[str, ...]]): An iterable of field
                paths (``.``-delimited list of field names) to use as a
                projection of document fields in the returned results. If
                no value is provided, all fields will be returned.
            transaction (Optional[~.firestore_v1beta1.transaction.\
                Transaction]): An existing transaction that these
                ``references`` will be retrieved in.

        Yields:
            .DocumentSnapshot: The next document snapshot that fulfills the
            query, or :data:`None` if the document does not exist.
        """
        document_paths, reference_map = _reference_info(references)
        mask = _get_doc_mask(field_paths)
        response_iterator = self._firestore_api.batch_get_documents(
            self._database_string, document_paths, mask,
            transaction=_helpers.get_transaction_id(transaction),
            metadata=self._rpc_metadata)

        for get_doc_response in response_iterator:
            yield _parse_batch_get(get_doc_response, reference_map, self)

    def batch(self):
        """Get a batch instance from this client.

        Returns:
            ~.firestore_v1beta1.batch.WriteBatch: A "write" batch to be
            used for accumulating document changes and sending the changes
            all at once.
        """
        return WriteBatch(self)

    def transaction(self, **kwargs):
        """Get a transaction that uses this client.

        See :class:`~.firestore_v1beta1.transaction.Transaction` for
        more information on transactions and the constructor arguments.

        Args:
            kwargs (Dict[str, Any]): The keyword arguments (other than
                ``client``) to pass along to the
                :class:`~.firestore_v1beta1.transaction.Transaction`
                constructor.

        Returns:
            ~.firestore_v1beta1.transaction.Transaction: A transaction
            attached to this client.
        """
        return Transaction(self, **kwargs)


class WriteOption(object):
    """Option used to assert a condition on a write operation."""

    def modify_write(self, write_pb, no_create_msg=None):
        """Modify a ``Write`` protobuf based on the state of this write option.

        This is a virtual method intended to be implemented by subclasses.

        Args:
            write_pb (google.cloud.firestore_v1beta1.types.Write): A
                ``Write`` protobuf instance to be modified with a precondition
                determined by the state of this option.
            no_create_msg (Optional[str]): A message to use to indicate that
                a create operation is not allowed.

        Raises:
            NotImplementedError: Always, this method is virtual.
        """
        raise NotImplementedError


class LastUpdateOption(WriteOption):
    """Option used to assert a "last update" condition on a write operation.

    This will typically be created by
    :meth:`~.firestore_v1beta1.client.Client.write_option`.

    Args:
        last_update_time (google.protobuf.timestamp_pb2.Timestamp): A
            timestamp. When set, the target document must exist and have
            been last updated at that time. Protobuf ``update_time`` timestamps
            are typically returned from methods that perform write operations
            as part of a "write result" protobuf or directly.
    """

    def __init__(self, last_update_time):
        self._last_update_time = last_update_time

    def modify_write(self, write_pb, **unused_kwargs):
        """Modify a ``Write`` protobuf based on the state of this write option.

        The ``last_update_time`` is added to ``write_pb`` as an "update time"
        precondition. When set, the target document must exist and have been
        last updated at that time.

        Args:
            write_pb (google.cloud.firestore_v1beta1.types.Write): A
                ``Write`` protobuf instance to be modified with a precondition
                determined by the state of this option.
            unused_kwargs (Dict[str, Any]): Keyword arguments accepted by
                other subclasses that are unused here.
        """
        current_doc = types.Precondition(
            update_time=self._last_update_time)
        write_pb.current_document.CopyFrom(current_doc)


class CreateIfMissingOption(WriteOption):
    """Option used to assert "create if missing" on a write operation.

    This will typically be created by
    :meth:`~.firestore_v1beta1.client.Client.write_option`.

    Args:
        create_if_missing (bool): Indicates if the document should be created
            if it doesn't already exist.
    """

    def __init__(self, create_if_missing):
        self._create_if_missing = create_if_missing

    def modify_write(self, write_pb, no_create_msg=None):
        """Modify a ``Write`` protobuf based on the state of this write option.

        If:

        * ``create_if_missing=False``, adds a precondition that requires
          existence
        * ``create_if_missing=True``, does not add any precondition
        * ``no_create_msg`` is passed, raises an exception. For example, in a
          :meth:`~.DocumentReference.delete`, no "create" can occur, so it
          wouldn't make sense to "create if missing".

        Args:
            write_pb (google.cloud.firestore_v1beta1.types.Write): A
                ``Write`` protobuf instance to be modified with a precondition
                determined by the state of this option.
            no_create_msg (Optional[str]): A message to use to indicate that
                a create operation is not allowed.

        Raises:
            ValueError: If ``no_create_msg`` is passed.
        """
        if no_create_msg is not None:
            raise ValueError(no_create_msg)
        elif not self._create_if_missing:
            current_doc = types.Precondition(exists=True)
            write_pb.current_document.CopyFrom(current_doc)


class ExistsOption(WriteOption):
    """Option used to assert existence on a write operation.

    This will typically be created by
    :meth:`~.firestore_v1beta1.client.Client.write_option`.

    This option is closely related to
    :meth:`~.firestore_v1beta1.client.CreateIfMissingOption`,
    but a "create if missing". In fact,

    .. code-block:: python

       >>> ExistsOption(exists=True)

    is (mostly) equivalent to

    .. code-block:: python

       >>> CreateIfMissingOption(create_if_missing=False)

    The only difference being that "create if missing" cannot be used
    on some operations (e.g. :meth:`~.DocumentReference.delete`)
    while "exists" can.

    Args:
        exists (bool): Indicates if the document being modified
            should already exist.
    """

    def __init__(self, exists):
        self._exists = exists

    def modify_write(self, write_pb, **unused_kwargs):
        """Modify a ``Write`` protobuf based on the state of this write option.

        If:

        * ``exists=True``, adds a precondition that requires existence
        * ``exists=False``, adds a precondition that requires non-existence

        Args:
            write_pb (google.cloud.firestore_v1beta1.types.Write): A
                ``Write`` protobuf instance to be modified with a precondition
                determined by the state of this option.
            unused_kwargs (Dict[str, Any]): Keyword arguments accepted by
                other subclasses that are unused here.
        """
        current_doc = types.Precondition(exists=self._exists)
        write_pb.current_document.CopyFrom(current_doc)


def _make_firestore_api(client):
    """Create an instance of the GAPIC Firestore client.

    Args:
        client (~.firestore_v1beta1.client.Client): The client that holds
            configuration details.

    Returns:
        ~.gapic.firestore.v1beta1.firestore_client.FirestoreClient: A
        Firestore GAPIC client instance with the proper credentials.
    """
    host = firestore_client.FirestoreClient.SERVICE_ADDRESS
    channel = make_secure_channel(
        client._credentials, DEFAULT_USER_AGENT, host)
    return firestore_client.FirestoreClient(
        channel=channel, lib_name='gccl', lib_version=__version__)


def _reference_info(references):
    """Get information about document references.

    Helper for :meth:`~.firestore_v1beta1.client.Client.get_all`.

    Args:
        references (List[.DocumentReference, ...]): Iterable of document
            references.

    Returns:
        Tuple[List[str, ...], Dict[str, .DocumentReference]]: A two-tuple of

        * fully-qualified documents paths for each reference in ``references``
        * a mapping from the paths to the original reference. (If multiple
          ``references`` contains multiple references to the same document,
          that key will be overwritten in the result.)
    """
    document_paths = []
    reference_map = {}
    for reference in references:
        doc_path = reference._document_path
        document_paths.append(doc_path)
        reference_map[doc_path] = reference

    return document_paths, reference_map


def _get_reference(document_path, reference_map):
    """Get a document reference from a dictionary.

    This just wraps a simple dictionary look-up with a helpful error that is
    specific to :meth:`~.firestore.client.Client.get_all`, the
    **public** caller of this function.

    Args:
        document_path (str): A fully-qualified document path.
        reference_map (Dict[str, .DocumentReference]): A mapping (produced
            by :func:`_reference_info`) of fully-qualified document paths to
            document references.

    Returns:
        .DocumentReference: The matching reference.

    Raises:
        ValueError: If ``document_path`` has not been encountered.
    """
    try:
        return reference_map[document_path]
    except KeyError:
        msg = _BAD_DOC_TEMPLATE.format(document_path)
        raise ValueError(msg)


def _parse_batch_get(get_doc_response, reference_map, client):
    """Parse a `BatchGetDocumentsResponse` protobuf.

    Args:
        get_doc_response (~google.cloud.proto.firestore.v1beta1.\
            firestore_pb2.BatchGetDocumentsResponse): A single response (from
            a stream) containing the "get" response for a document.
        reference_map (Dict[str, .DocumentReference]): A mapping (produced
            by :func:`_reference_info`) of fully-qualified document paths to
            document references.
        client (~.firestore_v1beta1.client.Client): A client that has
            a document factory.

    Returns:
        Optional[.DocumentSnapshot]: The retrieved snapshot. If the
        snapshot is :data:`None`, that means the document is ``missing``.

    Raises:
        ValueError: If the response has a ``result`` field (a oneof) other
            than ``found`` or ``missing``.
    """
    result_type = get_doc_response.WhichOneof('result')
    if result_type == 'found':
        reference = _get_reference(
            get_doc_response.found.name, reference_map)
        data = _helpers.decode_dict(get_doc_response.found.fields, client)
        snapshot = DocumentSnapshot(
            reference,
            data,
            exists=True,
            read_time=get_doc_response.read_time,
            create_time=get_doc_response.found.create_time,
            update_time=get_doc_response.found.update_time)
        return snapshot
    elif result_type == 'missing':
        return None
    else:
        raise ValueError(
            '`BatchGetDocumentsResponse.result` (a oneof) had a field other '
            'than `found` or `missing` set, or was unset')


def _get_doc_mask(field_paths):
    """Get a document mask if field paths are provided.

    Args:
        field_paths (Optional[Iterable[str, ...]]): An iterable of field
            paths (``.``-delimited list of field names) to use as a
            projection of document fields in the returned results.

    Returns:
        Optional[google.cloud.firestore_v1beta1.types.DocumentMask]: A mask
            to project documents to a restricted set of field paths.
    """
    if field_paths is None:
        return None
    else:
        return types.DocumentMask(field_paths=field_paths)
