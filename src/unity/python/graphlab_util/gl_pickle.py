'''
Copyright (C) 2015 Dato, Inc.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''
import graphlab as _gl
import inspect as _inspect
import graphlab_util.cloudpickle as _cloudpickle
import pickle as _pickle
import uuid as _uuid
import os as _os
import zipfile as _zipfile
import glob as _glob

def _is_gl_model_class(obj_class):
    """
    Check if class is a GraphLab create model. 

    The function does it by checking the method resolution order (MRO) of the
    class and verifies that _Model is the base class.  

    Parameters
    ----------
    obj_class    : Class to be checked. 

    Returns
    ----------
    True if the class is a GLC Model.

    """
    # If it has no base classes, then it is not a GLC Model.
    if not hasattr(obj_class, '__bases__'):
        return False

    # Check if _model.Model is a base class
    mro = _inspect.getmro(obj_class)
    if len(mro) > 2:
        return mro[-2] == _gl.toolkits._model.Model
    else:
        return False

def _is_gl_class(obj_class):
    """
    Check if class is a GraphLab create class. 

    A GLC class is either a GLC data structure class (SFrame, SGraph etc.) or
    a GLC model class.

    Parameters
    ----------
    obj_class    : Class to be checked. 

    Returns
    ----------
    True if the class is a GLC class.

    """
    # GLC-Data structures
    gl_ds = [_gl.SFrame, _gl.SArray, _gl.SGraph]

    # Object is GLC-DS or GLC-Model
    return (obj_class in gl_ds) or _is_gl_model_class(obj_class)

def _get_gl_class_type(obj_class):
    """
    Internal util to get the type of the GLC class. The pickle file stores
    this name so that it knows how to construct the object on unpickling.

    Parameters
    ----------
    obj_class    : Class which has to be categoriized.

    Returns
    ----------
    A class type for the pickle file to save.

    """

    if obj_class == _gl.SFrame:
        return "SFrame"
    elif obj_class == _gl.SGraph:
        return "SGraph"
    elif obj_class == _gl.SArray:
        return "SArray"
    elif _is_gl_model_class(obj_class):
        return "Model"
    else:
        return None

def _get_gl_object_from_persistent_id(type_tag, gl_archive_abs_path):
    """
    Internal util to get a GLC object from a persistent ID in the pickle file.

    Parameters
    ----------
    type_tag : The name of the glc class as saved in the GLC pickler.

    gl_archive_abs_path: An absolute path to the GLC archive where the 
                          object was saved.

    Returns
    ----------
    The GLC object.

    """
    if type_tag == "SFrame":
        obj = _gl.SFrame(gl_archive_abs_path)
    elif type_tag == "SGraph":
        obj = _gl.load_graph(gl_archive_abs_path)
    elif type_tag == "SArray":
        obj = _gl.SArray(gl_archive_abs_path)
    elif type_tag == "Model":
        obj = _gl.load_model(gl_archive_abs_path)
    else:
        raise _pickle.UnpicklingError("GraphLab pickling Error: Unspported object."
              " Only SFrames, SGraphs, SArrays, and Models are supported.")
    return obj

class GLPickler(_cloudpickle.CloudPickler):
    """

    # GLC pickle works with:
    #
    # (1) Regular python objects
    # (2) SArray
    # (3) SFrame
    # (4) SGraph
    # (5) Models
    # (6) Any combination of (1) - (5)
    
    Examples
    --------

    To pickle a collection of objects into a single file:
  
    .. sourcecode:: python

        from graphlab_util import gl_pickle
        import graphlab as gl
        
        obj = {'foo': gl.SFrame([1,2,3]),
               'bar': gl.SArray([1,2,3]),
               'foo-bar': ['foo-and-bar', gl.SFrame()]}
        
        # Setup the GLC pickler
        pickler = gl_pickle.GLPickler(filename = 'foo-bar')
        pickler.dump(obj)

        # The pickler has to be closed to make sure the files get closed.
        pickler.close()
        
    To unpickle the collection of objects:

    .. sourcecode:: python

        unpickler = gl_pickle.GLUnpickler(filename = 'foo-bar')
        obj = unpickler.load()
        print obj

    The GLC pickler needs a temoporary working directory to manage GLC objects.
    This temporary working path must be a local path to the file system. It
    can also be a relative path in the FS.

    .. sourcecode:: python

        unpickler = gl_pickle.GLUnpickler('foo-bar', 
                                             gl_temp_storage_path = '/tmp')
        obj = unpickler.load()
        print obj


    Notes
    --------

    The GLC pickler saves the files into single zip archive with the following
    file layout.

    pickle_file_name: Name of the file in the archive that contains
                      the name of the pickle file. 
                      The comment in the ZipFile contains the version number 
                      of the GLC pickler used.

    "pickle_file": The pickle file that stores all python objects. For GLC objects
                   the pickle file contains a tuple with (ClassName, relative_path)
                   which stores the name of the GLC object type and a relative
                   path (in the zip archive) which points to the GLC archive
                   root directory.

    "gl_archive_dir_1" : A directory which is the GLC archive for a single
                          object.
 
     ....

    "gl_archive_dir_N" 
                          
 

    """
    def __init__(self, filename, protocol = -1, min_bytes_to_save = 0, 
                 gl_temp_storage_path = '/tmp'):
        """

        Construct a  GLC pickler.

        Parameters
        ----------
        filename  : Name of the file to write to. This file is all you need to pickle
                    all objects (including GLC objects).

        protocol  : Pickle protocol (see pickle docs). Note that all pickle protocols
                    may not be compatable with GLC objects.

        min_bytes_to_save : Cloud pickle option (see cloud pickle docs)

        gl_temp_storage_path : Temporary storage for all GLC objects. The path
                                may be a relative path or an absolute path.

        Returns
        ----------
        GLC pickler.

        """

        # Need a temp storage path for GLC objects.
        self.gl_temp_storage_path = _os.path.abspath(gl_temp_storage_path)
        if not _os.path.exists(self.gl_temp_storage_path):
            raise RuntimeError('%s is not a valid path.' 
                                        % self.gl_temp_storage_path)

        # Save the archive name 
        self.archive_filename = filename

        # Chose a random file name to save the pickle contents.
        relative_pickle_filename = str(_uuid.uuid4())
        pickle_filename = _os.path.join(self.gl_temp_storage_path, 
                                                    relative_pickle_filename)
        try:
            # Initialize the pickle file with cloud _pickle. Note, cloud pickle
            # takes a file handle for intializzation (unlike GLC pickle which takes
            # a file name)
            self.file = open(pickle_filename, 'wb')
            _cloudpickle.CloudPickler.__init__(self, self.file, protocol)
        except IOError as err:
            print "GraphLab create pickling error: %s" % err

        # Save the name of the pickle file and the version number of the 
        # GLC pickler.
        zf = _zipfile.ZipFile(self.archive_filename, 'w') 
        try:
            info = _zipfile.ZipInfo('pickle_file')
            info.comment = "1.0" # Version
            zf.writestr(info, relative_pickle_filename)
        except IOError as err:
            print "GraphLab create pickling error: %s" % err
            self.file.close()
        finally:
            zf.close()

        
    def persistent_id(self, obj):
        """
        Provide a persistant ID for "saving" GLC objects by reference. Return
        None for all non GLC objects.

        Parameters
        ----------

        obj: Name of the object whose persistant ID is extracted.

        Returns
        --------
        None if the object is not a GLC object. (ClassName, relative path)
        if the object is a GLC object.

        Notes
        -----

        Borrowed from pickle docs (https://docs.python.org/2/library/_pickle.html)

        For the benefit of object persistence, the pickle module supports the
        notion of a reference to an object outside the pickled data stream.

        To pickle objects that have an external persistent id, the pickler must
        have a custom persistent_id() method that takes an object as an argument and
        returns either None or the persistent id for that object. 

        For GLC objects, the persistent_id is merely a relative file path (within
        the ZIP archive) to the GLC archive where the GLC object is saved. For
        example:
    
            (SFrame, 'sframe-save-path')
            (SGraph, 'sgraph-save-path')
            (Model, 'model-save-path')

        """

        # Get the class of the object (if it can be done)
        obj_class = None if not hasattr(obj, '__class__') else obj.__class__
        if obj_class is None:
            return None

        # If the object is a GLC class.
        if _is_gl_class(obj_class):
            # Save the location of the GLC object's archive to the pickle file.
            relative_filename = str(_uuid.uuid4())
            filename = _os.path.join(self.gl_temp_storage_path, relative_filename)

            # Save the GLC object and then write to a zip archive
            obj.save(filename)
            for abs_name in _glob.glob(_os.path.join(filename, '*')):
                zf = _zipfile.ZipFile(self.archive_filename, mode='a')
                rel_name = _os.path.relpath(abs_name, self.gl_temp_storage_path)
                zf.write(abs_name, rel_name)
                zf.close()

            # Return the tuple (class_name, relative_filename) in archive. 
            return (_get_gl_class_type(obj.__class__), relative_filename) 

        # Not a GLC object. Default to cloud pickle
        else:
            return None

    def close(self):
        """
        Close the pickle file, and the zip archive file. The single zip archive
        file can now be shipped around to be loaded by the unpickler.
        """
        # Close the pickle file.
        self.file.close()

        # Add the pickle file name to the zip file archive.
        zf = _zipfile.ZipFile(self.archive_filename, mode='a')
        try:
            abs_name = self.file.name
            rel_name = _os.path.relpath(abs_name, self.gl_temp_storage_path)
            zf.write(abs_name, rel_name)
        except: 
            raise IOError("GraphLab pickling error: Unable to add the pickle"
                          " file to the archive.")
        finally:
            zf.close()

class GLUnpickler(_pickle.Unpickler):
    """
    # GLC unpickler works with a GLC pickler archive or a regular pickle 
    # archive.
    #
    # Works with 
    # (1) GLPickler archive 
    # (2) Cloudpickle archive
    # (3) Python pickle archive

    Examples
    --------
    To unpickle the collection of objects:

    .. sourcecode:: python

        unpickler = gl_pickle.GLUnpickler('foo-bar')
        obj = unpickler.load()
        print obj
                          
    """

    def __init__(self, filename, gl_temp_storage_path = '/tmp/'):
        """
        Construct a GLC unpickler.

        Parameters
        ----------
        filename  : Name of the file to read from. The file can be a GLC pickle
                    file, a cloud pickle file, or a python pickle file.

        gl_temp_storage_path : Temporary storage for all GLC objects. The path
                               may be a relative path or an absolute path.

        Returns
        ----------
        GLC unpickler.
        """

        # Need a temp storage path for GLC objects.
        self.gl_temp_storage_path = _os.path.abspath(gl_temp_storage_path)
        if not _os.path.exists(self.gl_temp_storage_path):
            raise RuntimeError('%s is not a valid path.' 
                                        % self.gl_temp_storage_path)
                                    
        # Check that the archive file is valid.
        if not _os.path.exists(filename):
            raise RuntimeError('%s is not a valid file name.' 
                                        % filename)

        # If the file is a Zip archive, then it will try to use the GLC 
        # unpickler, else it will use regular unpickler.
        if _zipfile.is_zipfile(filename):

            pickle_filename = None

            # Get the pickle file name.
            zf = _zipfile.ZipFile(filename)
            for info in zf.infolist():
                if info.filename == 'pickle_file':
                    pickle_filename = zf.read(info.filename)
            if pickle_filename is None:
                raise IOError("Cannot pickle file of the given format. File must be one of (a) GLPickler archive"
                             ", (b) Cloudpickle archive, or (c) python pickle archive.")
        
            # Extract the files ihe zip archive
            try:
                outpath = self.gl_temp_storage_path
                zf.extractall(outpath)
            except IOError as err:
                print "Graphlab pickle extraction error: %s " % err

            # Open the pickle file
            abs_pickle_filename = _os.path.join(self.gl_temp_storage_path, pickle_filename)
            _pickle.Unpickler.__init__(self, open(abs_pickle_filename, 'rb'))

        # Not an archived pickle file. Use _pickle.Unpickler to do 
        # everything.
        else: 
            _pickle.Unpickler.__init__(self, open(filename, 'rb'))

    def persistent_load(self, pid):
        """
        Reconstruct a GLC object using the persistent ID.

        Parameters
        ----------
        pid      : The persistent ID used in pickle file to save the GLC object.

        Returns
        ----------
        The GLC object.
        """
        type_tag, filename = pid
        abs_path = _os.path.join(self.gl_temp_storage_path, filename) 
        return _get_gl_object_from_persistent_id(type_tag, abs_path)


