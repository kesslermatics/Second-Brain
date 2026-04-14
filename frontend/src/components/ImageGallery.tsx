'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import {
  FiUpload, FiTrash2, FiRefreshCw, FiImage, FiInfo, FiX,
  FiCheck, FiClock, FiSearch, FiZoomIn,
} from 'react-icons/fi';
import { getImages, uploadImage, deleteImage, reanalyzeImage } from '@/lib/api';
import type { ImageItem } from '@/lib/types';

export default function ImageGallery() {
  const [images, setImages] = useState<ImageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [selectedImage, setSelectedImage] = useState<ImageItem | null>(null);
  const [filter, setFilter] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadImages = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await getImages();
      setImages(resp.images);
      setTotal(resp.total);
    } catch (e) {
      console.error('Failed to load images:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadImages();
  }, [loadImages]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    setUploading(true);
    try {
      for (let i = 0; i < files.length; i++) {
        await uploadImage(files[i]);
      }
      await loadImages();
    } catch (e) {
      console.error('Upload failed:', e);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (imageId: string) => {
    if (!confirm('Bild wirklich löschen?')) return;
    try {
      await deleteImage(imageId);
      setImages(prev => prev.filter(img => img.id !== imageId));
      if (selectedImage?.id === imageId) setSelectedImage(null);
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  const handleReanalyze = async (imageId: string) => {
    try {
      const updated = await reanalyzeImage(imageId);
      setImages(prev => prev.map(img => img.id === imageId ? updated : img));
      if (selectedImage?.id === imageId) setSelectedImage(updated);
    } catch (e) {
      console.error('Reanalyze failed:', e);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const filteredImages = filter
    ? images.filter(img =>
      img.original_filename.toLowerCase().includes(filter.toLowerCase()) ||
      (img.description && img.description.toLowerCase().includes(filter.toLowerCase()))
    )
    : images;

  return (
    <div className="h-full flex flex-col bg-dark-950">
      {/* Header */}
      <div className="px-6 py-4 border-b border-dark-800 bg-dark-900/50">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-600/20 rounded-xl">
              <FiImage className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">Bilder-Galerie</h1>
              <p className="text-xs text-dark-500">{total} Bilder — AI-interpretiert für RAG</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => loadImages()}
              className="p-2 text-dark-400 hover:text-white hover:bg-dark-800 rounded-lg transition-colors"
              title="Aktualisieren"
            >
              <FiRefreshCw className="w-4 h-4" />
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex items-center gap-1.5 px-3 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
            >
              {uploading ? (
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <FiUpload className="w-4 h-4" />
              )}
              {uploading ? 'Lädt hoch...' : 'Hochladen'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={handleUpload}
            />
          </div>
        </div>

        {/* Search filter */}
        <div className="relative">
          <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-500" />
          <input
            type="text"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Bilder durchsuchen (Name oder Beschreibung)..."
            className="w-full pl-9 pr-4 py-2 bg-dark-800 border border-dark-700 rounded-lg text-sm text-white placeholder-dark-500 focus:outline-none focus:border-indigo-500"
          />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : filteredImages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-dark-500">
            <FiImage className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">
              {filter ? 'Keine Bilder gefunden' : 'Noch keine Bilder hochgeladen'}
            </p>
            {!filter && (
              <p className="text-xs mt-1">
                Lade Bilder hoch — sie werden automatisch von AI analysiert und im RAG verfügbar gemacht.
              </p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {filteredImages.map(img => (
              <ImageCard
                key={img.id}
                image={img}
                onSelect={() => setSelectedImage(img)}
                onDelete={() => handleDelete(img.id)}
                onReanalyze={() => handleReanalyze(img.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Detail panel */}
      {selectedImage && (
        <ImageDetail
          image={selectedImage}
          onClose={() => setSelectedImage(null)}
          onDelete={() => handleDelete(selectedImage.id)}
          onReanalyze={() => handleReanalyze(selectedImage.id)}
        />
      )}
    </div>
  );
}

/* ── Image Card ──────────────────────────────────────────────── */

function ImageCard({
  image,
  onSelect,
  onDelete,
  onReanalyze,
}: {
  image: ImageItem;
  onSelect: () => void;
  onDelete: () => void;
  onReanalyze: () => void;
}) {
  return (
    <div className="group relative bg-dark-900 rounded-xl border border-dark-800 overflow-hidden hover:border-indigo-500/50 transition-colors">
      {/* Thumbnail */}
      <div
        className="relative aspect-square cursor-pointer overflow-hidden"
        onClick={onSelect}
      >
        <img
          src={image.url}
          alt={image.original_filename}
          className="w-full h-full object-cover transition-transform group-hover:scale-105"
          loading="lazy"
        />
        {/* Status badge */}
        <div className="absolute top-2 right-2">
          {image.embedded ? (
            <div className="p-1 bg-green-600/80 rounded-full" title="In RAG eingebettet">
              <FiCheck className="w-3 h-3 text-white" />
            </div>
          ) : (
            <div className="p-1 bg-yellow-600/80 rounded-full animate-pulse" title="Wird analysiert...">
              <FiClock className="w-3 h-3 text-white" />
            </div>
          )}
        </div>
        {/* Hover overlay */}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
          <FiZoomIn className="w-6 h-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
      </div>

      {/* Info */}
      <div className="p-2.5">
        <p className="text-xs text-white truncate font-medium">{image.original_filename}</p>
        <p className="text-[10px] text-dark-500 mt-0.5">
          {formatDateShort(image.created_at)} · {formatSizeShort(image.file_size)}
        </p>
        {image.description && (
          <p className="text-[10px] text-dark-400 mt-1 line-clamp-2">{image.description}</p>
        )}
      </div>

      {/* Quick actions overlay */}
      <div className="absolute top-2 left-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={(e) => { e.stopPropagation(); onReanalyze(); }}
          className="p-1.5 bg-dark-900/80 hover:bg-indigo-600 rounded-lg transition-colors"
          title="Erneut analysieren"
        >
          <FiRefreshCw className="w-3 h-3 text-white" />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="p-1.5 bg-dark-900/80 hover:bg-red-600 rounded-lg transition-colors"
          title="Löschen"
        >
          <FiTrash2 className="w-3 h-3 text-white" />
        </button>
      </div>
    </div>
  );
}

/* ── Image Detail Panel ──────────────────────────────────────── */

function ImageDetail({
  image,
  onClose,
  onDelete,
  onReanalyze,
}: {
  image: ImageItem;
  onClose: () => void;
  onDelete: () => void;
  onReanalyze: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div
        className="bg-dark-900 rounded-2xl border border-dark-800 max-w-4xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-dark-800">
          <div className="flex items-center gap-2">
            <FiImage className="w-4 h-4 text-indigo-400" />
            <span className="text-sm font-medium text-white truncate max-w-md">
              {image.original_filename}
            </span>
            {image.embedded && (
              <span className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-green-600/20 text-green-400 rounded-full">
                <FiCheck className="w-3 h-3" /> RAG
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onReanalyze}
              className="p-1.5 text-dark-400 hover:text-indigo-400 hover:bg-dark-800 rounded-lg transition-colors"
              title="Erneut analysieren"
            >
              <FiRefreshCw className="w-4 h-4" />
            </button>
            <button
              onClick={onDelete}
              className="p-1.5 text-dark-400 hover:text-red-400 hover:bg-dark-800 rounded-lg transition-colors"
              title="Löschen"
            >
              <FiTrash2 className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-dark-400 hover:text-white hover:bg-dark-800 rounded-lg transition-colors"
            >
              <FiX className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto flex flex-col md:flex-row">
          {/* Image */}
          <div className="md:flex-1 flex items-center justify-center p-4 bg-dark-950">
            <img
              src={image.url}
              alt={image.original_filename}
              className="max-w-full max-h-[60vh] object-contain rounded-lg"
            />
          </div>

          {/* Description panel */}
          <div className="md:w-80 border-t md:border-t-0 md:border-l border-dark-800 p-4 space-y-4">
            <div>
              <h3 className="text-xs font-semibold text-dark-500 uppercase tracking-wider mb-1">Details</h3>
              <div className="space-y-1 text-sm text-dark-300">
                <p><span className="text-dark-500">Typ:</span> {image.content_type}</p>
                <p><span className="text-dark-500">Größe:</span> {formatSizeShort(image.file_size)}</p>
                <p><span className="text-dark-500">Datum:</span> {new Date(image.created_at).toLocaleString('de-DE')}</p>
              </div>
            </div>

            <div>
              <h3 className="text-xs font-semibold text-dark-500 uppercase tracking-wider mb-1 flex items-center gap-1.5">
                <FiInfo className="w-3 h-3" />
                AI-Beschreibung
              </h3>
              {image.description ? (
                <p className="text-sm text-dark-300 leading-relaxed whitespace-pre-wrap">
                  {image.description}
                </p>
              ) : (
                <div className="flex items-center gap-2 text-sm text-yellow-400">
                  <div className="w-3 h-3 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
                  Wird analysiert...
                </div>
              )}
            </div>

            {image.embedded && (
              <div className="p-3 bg-green-600/10 border border-green-600/20 rounded-lg">
                <p className="text-xs text-green-400">
                  Dieses Bild ist im RAG-System eingebettet. Die AI-Beschreibung wird bei Suchanfragen und im Chat berücksichtigt.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Helpers ─────────────────────────────────────────────────── */

function formatDateShort(dateStr: string) {
  const d = new Date(dateStr);
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' });
}

function formatSizeShort(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
