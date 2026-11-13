import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ActionIcon, Tooltip } from '@mantine/core';
import { IconGripVertical } from '@tabler/icons-react';
import { createContext, useContext, useState, type CSSProperties, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { refreshViews, send } from '../api';
import { showError } from './Common';

const SavingContext = createContext(false);

/** Persist a collection's visual order without changing its item configuration. */
export function SortableCards<T extends { id: string }>({
  items,
  endpoint,
  children,
}: {
  items: T[];
  endpoint: string;
  children: (ordered: T[]) => ReactNode;
}) {
  const { t } = useTranslation();
  const [order, setOrder] = useState<string[] | null>(null);
  const [saving, setSaving] = useState(false);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const indexed = new Map(items.map((item) => [item.id, item]));
  const ordered = order
    ? [
        ...order.flatMap((id) => (indexed.has(id) ? [indexed.get(id)!] : [])),
        ...items.filter((item) => !order.includes(item.id)),
      ]
    : items;
  const ids = ordered.map((item) => item.id);
  return (
    <SavingContext.Provider value={saving}>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        accessibility={{
          screenReaderInstructions: {
            draggable: t(
              'Press Space to pick up a card, use arrow keys to move it, Space to drop, or Escape to cancel.',
            ),
          },
          announcements: {
            onDragStart: () => t('Card picked up.'),
            onDragOver: ({ over }) =>
              over
                ? t('Card position {{position}}.', { position: ids.indexOf(String(over.id)) + 1 })
                : undefined,
            onDragEnd: () => t('Card dropped.'),
            onDragCancel: () => t('Reordering cancelled.'),
          },
        }}
        onDragStart={() => setOrder(ids)}
        onDragCancel={() => setOrder(null)}
        onDragEnd={async ({ active, over }) => {
          const from = ids.indexOf(String(active.id));
          const to = over ? ids.indexOf(String(over.id)) : -1;
          if (saving || from < 0 || to < 0 || from === to) {
            setOrder(null);
            return;
          }
          const next = arrayMove(ids, from, to);
          setOrder(next);
          setSaving(true);
          try {
            await send(endpoint, { ids: next }, 'PUT');
          } catch (error) {
            showError(error);
          } finally {
            await refreshViews();
            setOrder(null);
            setSaving(false);
          }
        }}
      >
        <SortableContext items={ids} strategy={rectSortingStrategy}>
          {children(ordered)}
        </SortableContext>
      </DndContext>
    </SavingContext.Provider>
  );
}

/** Bind movement only to a focusable handle so card controls keep their behavior. */
export function useSortableCard(id: string, name: string) {
  const { t } = useTranslation();
  const saving = useContext(SavingContext);
  const sortable = useSortable({ id, disabled: saving });
  const style: CSSProperties = {
    transform: CSS.Transform.toString(sortable.transform),
    transition: sortable.transition,
    position: 'relative',
    zIndex: sortable.isDragging ? 2 : undefined,
    opacity: sortable.isDragging ? 0.75 : 1,
  };
  return {
    ref: sortable.setNodeRef,
    style,
    handle: (
      <Tooltip label={t('Drag to reorder')}>
        <ActionIcon
          ref={sortable.setActivatorNodeRef}
          variant="subtle"
          color="gray"
          disabled={saving}
          {...sortable.attributes}
          {...sortable.listeners}
          aria-label={`${t('Move')} ${name}`}
          style={{ touchAction: 'none', cursor: sortable.isDragging ? 'grabbing' : 'grab' }}
        >
          <IconGripVertical size={18} />
        </ActionIcon>
      </Tooltip>
    ),
  };
}
