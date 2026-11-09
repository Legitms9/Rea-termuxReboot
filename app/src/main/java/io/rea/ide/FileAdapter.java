package io.rea.ide;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;

/** Explorer list. */
public class FileAdapter extends RecyclerView.Adapter<FileAdapter.VH> {

    public interface Listener {
        void onOpen(Workspace.Entry entry);
        void onLongPress(Workspace.Entry entry);
    }

    private final List<Workspace.Entry> items = new ArrayList<>();
    private final Listener listener;

    public FileAdapter(Listener listener) {
        this.listener = listener;
        setHasStableIds(false);
    }

    public void submit(List<Workspace.Entry> entries) {
        items.clear();
        items.addAll(entries);
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View v = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_file, parent, false);
        return new VH(v);
    }

    @Override
    public void onBindViewHolder(@NonNull VH h, int position) {
        Workspace.Entry e = items.get(position);
        h.icon.setText(e.directory ? "▸" : iconFor(e.name));
        h.icon.setTextColor(e.directory
                ? h.itemView.getContext().getColor(R.color.rea_accent)
                : h.itemView.getContext().getColor(R.color.rea_text_dim));
        h.name.setText(e.name);
        h.meta.setText(e.subtitle());
        h.itemView.setOnClickListener(v -> listener.onOpen(e));
        h.itemView.setOnLongClickListener(v -> {
            listener.onLongPress(e);
            return true;
        });
    }

    private static String iconFor(String name) {
        String n = name.toLowerCase();
        if (n.endsWith(".md")) return "M";
        if (n.endsWith(".json") || n.endsWith(".yml") || n.endsWith(".yaml") || n.endsWith(".toml")) return "{";
        if (n.endsWith(".sh") || n.endsWith(".bash")) return "$";
        if (n.endsWith(".html") || n.endsWith(".htm")) return "<";
        if (n.endsWith(".css") || n.endsWith(".scss")) return "#";
        if (n.endsWith(".js") || n.endsWith(".ts") || n.endsWith(".jsx") || n.endsWith(".tsx")) return "JS";
        if (n.endsWith(".py")) return "Py";
        if (n.endsWith(".java") || n.endsWith(".kt")) return "J";
        if (n.endsWith(".c") || n.endsWith(".cpp") || n.endsWith(".h") || n.endsWith(".rs")) return "C";
        return "·";
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static class VH extends RecyclerView.ViewHolder {
        final TextView icon;
        final TextView name;
        final TextView meta;

        VH(View v) {
            super(v);
            icon = v.findViewById(R.id.file_icon);
            name = v.findViewById(R.id.file_name);
            meta = v.findViewById(R.id.file_meta);
        }
    }
}
